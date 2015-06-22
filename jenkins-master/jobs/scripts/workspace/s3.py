# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import gzip
import logging
import os
import re
import sys
import tempfile

from optparse import OptionParser

import boto
import boto.s3.connection

# Set the logger globally in the file, but this must be reset when
# used in a child process.
logger = logging.getLogger()


class S3Error(Exception):
    def __init__(self, message):
        Exception.__init__(self, 'S3Error: %s' % message)


class S3Bucket(object):

    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self._bucket = None
        self.access_key_id = os.environ['AWS_ACCESS_KEY_ID']
        self.access_secret_key = os.environ['AWS_SECRET_ACCESS_KEY']

    @property
    def bucket(self):
        if self._bucket:
            return self._bucket
        try:
            conn = boto.s3.connection.S3Connection(self.access_key_id,
                                                   self.access_secret_key)
            if not conn.lookup(self.bucket_name):
                raise S3Error('bucket %s not found' % self.bucket_name)
            if not self._bucket:
                self._bucket = conn.get_bucket(self.bucket_name)
            return self._bucket
        except boto.exception.NoAuthHandlerFound:
            logger.exception()
            raise S3Error('Authentication failed')
        except boto.exception.S3ResponseError, e:
            logger.exception()
            raise S3Error('%s' % e)

    def ls(self, keypattern='.*'):
        if isinstance(keypattern, str):
            keypattern = re.compile(keypattern)
        keys = [key for key in self.bucket.list() if keypattern.match(key.name)]
        return keys

    def rm(self, keys):
        assert isinstance(keys, list) or isinstance(keys, str)

        if isinstance(keys, str):
            keys = self.ls(keys)
        try:
            for key in keys:
                key.delete()
        except boto.exception.S3ResponseError, e:
            logger.exception(str(e))
            raise S3Error('%s' % e)

    def upload(self, path, destination):
        try:
            key = self.bucket.get_key(destination)
            if not key:
                logger.debug('Creating key: %s' % destination)
                key = self.bucket.new_key(destination)

            ext = os.path.splitext(path)[-1]
            if ext == '.log' or ext == '.txt':
                key.set_metadata('Content-Type', 'text/plain')

            with tempfile.NamedTemporaryFile('w+b', suffix=ext) as tf:
                logger.debug('Compressing: %s' % path)
                with gzip.GzipFile(path, 'wb', fileobj=tf) as gz:
                    with open(path, 'rb') as f:
                        gz.writelines(f)
                tf.flush()
                tf.seek(0)
                key.set_metadata('Content-Encoding', 'gzip')
                logger.debug('Setting key contents from: %s' % tf.name)
                key.set_contents_from_file(tf)

            url = key.generate_url(expires_in=0,
                                   query_auth=False)
        except boto.exception.S3ResponseError, e:
            logger.exception(str(e))
            raise S3Error('%s' % e)

        logger.debug('File %s uploaded to: %s' % (path, url))
        return url

if __name__ == '__main__':
    logging.basicConfig()
    logger.setLevel(logging.INFO)

    parser = OptionParser()
    parser.set_usage("""
    usage: %prog [options]

    --s3-upload-bucket, --aws-access-key-id, --aws-access-key must be specified
    together either as command line options or in the --config file.

    --upload and --key must be specified together.
    """)
    parser.add_option('--bucket',
                      dest='bucket',
                      default=None,
                      help="""AWS S3 bucket name used to store files.
                      Defaults to None. If specified, --aws-access-key-id
                      and --aws-secret-access-key must also be specified.
                      """)
    parser.add_option('--ls',
                      dest='ls',
                      action='store',
                      type='string',
                      default=None,
                      help='List matching keys in bucket.')
    parser.add_option('--rm',
                      dest='rm',
                      action='store',
                      type='string',
                      default=None,
                      help='Delete matching keys in bucket.')
    parser.add_option('--upload',
                      dest='upload',
                      action='store',
                      type='string',
                      default=None,
                      help="""File to upload file to bucket.
                      If --upload is specified, --key must also
                      be specified.""")
    parser.add_option('--key',
                      dest='key',
                      action='store',
                      type='string',
                      default=None,
                      help="""Bucket key for uploaded file.
                      If --upload is specified, --key must also
                      be specified.""")

    (cmd_options, args) = parser.parse_args()

    if ((cmd_options.upload or cmd_options.key) and (
            not cmd_options.upload or not cmd_options.key)):
        parser.error('--upload and --key must be specified together.')
        parser.print_usage()
        sys.exit(1)

    if (not cmd_options.bucket and
            not cmd_options.ls and
            not cmd_options.rm and
            not cmd_options.upload and
            not cmd_options.key):
        parser.print_usage()
        sys.exit(1)

    logger.debug('bucket %s' % cmd_options.bucket)

    s3bucket = S3Bucket(cmd_options.bucket)

    if cmd_options.upload:
        print s3bucket.upload(cmd_options.upload, cmd_options.key)
    if cmd_options.ls:
        for key in s3bucket.ls(cmd_options.ls):
            print key.name
    if cmd_options.rm:
        s3bucket.rm(cmd_options.rm)
