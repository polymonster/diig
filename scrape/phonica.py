import urllib.request
from requests_html import HTMLSession

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC 

# scrape an individual page for a view (essentials, new releases)
def scrape_page(url, store, view, section, counter, session_scraped_ids):
    print(f"scraping phonica: {section} {url}")

    '''
    session = HTMLSession()
    response = session.get(url)
    # Check if the response is a 307 redirect
    if response.status_code == 307:
        redirect_url = response.headers.get("Location")  # Get the new location
        print(redirect_url)
    '''
    # Initialize WebDriver
    driver = webdriver.Chrome()
    driver.get(url)
    html = driver.execute_script("return document.documentElement.outerHTML")
    print(html)
    driver.minimize_window()

    '''
    # Find all elements matching a specific selector (e.g., all <div> elements)
    elements = WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div.product-place=holder"))
    )
    '''
    # Extract the text of each element and store it in a list
    # elements_text = [element.text for element in elements]

    # Print the list of texts
    # print(elements_text)

    driver.quit()

    # try and then continue if the page does not exist
    '''
    try:
        req = urllib.request.Request(
            url=url,
            headers={'User-Agent': 'Mozilla/5.0'}
        )
        html_file = urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        print(e.code)
        print(e.read())
        print("request failed")
        return -1
    
    print(html_file)
    '''

    pass