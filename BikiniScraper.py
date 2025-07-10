from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
import time

# === USER CREDENTIALS ===
email = "immy@serifovic.com"
password = "Webdb123"

# Optional: hide browser window (for faster runs, remove for debugging)
options = Options()
# options.add_argument("--headless")

# Launch Chrome
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# Hide potential popups/overlays that block form inputs
driver.execute_script("""
  var k = document.getElementById('klaviyoNewsletterPopup');
  if (k) k.style.display = 'none';
  var f = document.querySelector('.fostr-modal, .fostr-modal-active');
  if (f) f.style.display = 'none';
""")

# === GO TO GIVEAWAY ENTRY PAGE AND CLICK 'SIGN IN' ===
driver.get("https://triangl.com/collections/giveaway")
time.sleep(1)



#Click the "Already have an account? Sign in" button
try:
    sign_in_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Already')]"))
    )
    driver.execute_script("arguments[0].scrollIntoView(true);", sign_in_button)
    from selenium.webdriver.common.action_chains import ActionChains
    ActionChains(driver).move_to_element(sign_in_button).click().perform()

    # Wait for login form to appear
    login_form = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "customer_login"))
    )

    # Fill credentials
    email_input = login_form.find_element(By.ID, "CustomerEmail")
    password_input = login_form.find_element(By.ID, "CustomerPassword")
    email_input.send_keys(email)
    password_input.send_keys(password, Keys.RETURN)
    print("Submitted login form via Enter key.")
    time.sleep(2)
except Exception as e:
    print("Error during login:", e)
    driver.save_screenshot("login_fail.png")
time.sleep(2)





# === SELECT FIRST AVAILABLE BIKINI ===
# Scroll down in case items are lazy-loaded
driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
time.sleep(0.3)

# Find all product links and click the first one (updated selector)
product_links = driver.find_elements(By.CSS_SELECTOR, "a.util-FauxLink_Link")
if product_links:
    print(f"Found {len(product_links)} products.")
    product_links[0].click()
    print("Clicked first bikini product.")
else:
    print("No products found on giveaway page.")
time.sleep(1)

# === SELECT SIZE AND ADD TO CART ===
# Click Medium top size label
try:
    top_sizes = WebDriverWait(driver, 10).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[name='Size-top'] + label"))
    )
    for option in top_sizes:
        if "S" in option.text:
            option.click()
            print("Selected top size M.")
            break
except:
    print("No top sizes found.")

# Click Medium bottom size label
try:
    bottom_sizes = WebDriverWait(driver, 5).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "input[name='Size-bottom'] + label"))
    )
    for option in bottom_sizes:
        if "S" in option.text:
            option.click()
            print("Selected bottom size M.")
            break
except:
    print("No bottom sizes found.")

# Click the 'Add to Cart' button
try:
    add_to_cart = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit'].product-form__submit"))
    )
    add_to_cart.click()
    print("Clicked 'Add to Cart'.")
except:
    print("Could not click 'Add to Cart'.")
time.sleep(1)

# Click the "Check Out" button
try:
    checkout_button = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.XPATH, "//div[@class='cart__ctas']//button[contains(text(), 'Check out')]"))
    )
    checkout_button.click()
    print("Clicked 'Check Out'.")
except:
    print("Could not click 'Check Out'.")
time.sleep(1)

# === FILL OUT CHECKOUT FORM ===
try:
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.NAME, "email"))
    )

    driver.find_element(By.NAME, "email").send_keys("anissa.wang@gmail.com")
    driver.find_element(By.NAME, "firstName").send_keys("Anissa")
    driver.find_element(By.NAME, "lastName").send_keys("Wang")
    driver.find_element(By.NAME, "address1").send_keys("262 West 71st Street")
    driver.find_element(By.NAME, "city").send_keys("New York")
    driver.find_element(By.NAME, "province").send_keys("New York")

    print("Filled out shipping form.")
except Exception as e:
    print("Error filling checkout form:", e)

# === FILL PAYMENT FORM (INSIDE IFRAMES) ===
try:
    # CARD NUMBER
    card_number_frame = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[name*='card-fields-number']"))
    )
    driver.switch_to.frame(card_number_frame)
    card_number_input = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.NAME, "number"))
    )
    card_number_input.send_keys("4242424242424242")
    driver.switch_to.default_content()

    # EXPIRY DATE
    exp_frame = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[name*='card-fields-expiry']"))
    )
    driver.switch_to.frame(exp_frame)
    exp_input = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.NAME, "expiry")))
    for char in "1230":
        exp_input.send_keys(char)
        time.sleep(0.1)
    driver.switch_to.default_content()

    # CVC
    cvc_frame = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[name*='card-fields-verification']"))
    )
    driver.switch_to.frame(cvc_frame)
    cvc_input = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.NAME, "verification_value")))
    cvc_input.send_keys("123")
    driver.switch_to.default_content()

    print("Filled payment form.")
except Exception as e:
    print("Error filling payment form:", e)

time.sleep(1000)
# Optional: take a screenshot for debugging
driver.save_screenshot("giveaway_page.png")

# Done for now
driver.quit()

# Note: Payment fields are inside iframes and require switching context to fill.
# These must be handled separately with:
# driver.switch_to.frame(driver.find_element(By.CSS_SELECTOR, "iframe[name*='card-fields-number']"))
# And similarly for exp-month, exp-year, and CVV fields.