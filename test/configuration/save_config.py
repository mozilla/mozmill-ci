from selenium import webdriver


def main():
    base_url = 'http://localhost:8080/'

    driver = webdriver.PhantomJS()
    driver.implicitly_wait(10)

    # TODO: Uncomment when #263 and #345 are resolved
    # * Replace the Node Offline notification plugin with Mail Watcher plugin
    #   https://github.com/mozilla/mozmill-ci/issues/263
    # * Upgrade Email-ext plugin to 2.36
    #   https://github.com/mozilla/mozmill-ci/issues/345

    # print 'Saving master node configuration...'
    # driver.get(base_url + 'computer/%28master%29/configure')
    # driver.find_element_by_css_selector(
    #     '.submit-button button').click()

    # print 'Saving main configuration...'
    # driver.get(base_url + 'configure')
    # driver.find_element_by_css_selector(
    #     '#bottom-sticker .submit-button button').click()

    print 'Saving job configurations...'
    driver.get(base_url)
    job_links = driver.find_elements_by_css_selector(
        "tr[id*='job_'] > td:nth-child(3) > a")
    job_urls = [link.get_attribute('href') for link in job_links]

    for i, url in enumerate(job_urls):
        driver.get(url + 'configure')
        print '[%d/%d] %s' % (
            i + 1, len(job_urls),
            driver.find_element_by_name('name').get_attribute('value'))
        driver.find_element_by_css_selector(
            '#bottom-sticker .submit-button button').click()
        driver.find_element_by_css_selector('#main-panel h1')

    driver.quit()


if __name__ == "__main__":
    main()
