import requests

def get_jiomart_price(product_url: str, pincode: str = "695583"):
    session = requests.Session()

    # Set headers to mimic a real browser
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9"
    })

    # Step 1: Manually inject location cookies
    session.cookies.set("nms_mgo_city", "Thiruvananthapuram")
    session.cookies.set("nms_mgo_state_code", "KL")
    session.cookies.set("nms_mgo_pincode", pincode)
    session.cookies.set("new_customer", "false")

    # Step 2: Visit homepage or any page to allow session cookies to populate
    session.get("https://www.jiomart.com")

    # Step 3: Now call the product URL
    response = session.get(product_url)

    return {
        "status": response.status_code,
        "cookies": session.cookies.get_dict(),
        "content": response.text[:1000]  # limit output
    }

# Example usage
product_url = "https://www.jiomart.com/p/groceries/yogabar-protein-muesli-350-g/608274052"
result = get_jiomart_price(product_url)
print(result["cookies"])
  # print only part of the HTML
