from email.message import EmailMessage

from settings import MAILER_ADDRESS, MAILER_PASSWORD
import aiosmtplib

from base_models import MailTemplate


async def send_mail_async(data: MailTemplate) -> None:
    """Send a transactional e‑mail **asynchronously**.

    This runs entirely inside the asyncio event‑loop – no threads, no blocking.
    Raise `aiosmtplib.SMTPException` on failure so the caller can log / retry.
    """
    msg = EmailMessage()
    msg['Subject'] = 'Price Drop Alert From JioMart'
    msg['From'] = MAILER_ADDRESS
    msg['To'] = data.user_email
    msg.set_content('This is a fallback plain-text message for clients that do not support HTML.')
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8" />
        <meta name="x-apple-disable-message-reformatting" />
        <title>Price Drop Alert</title>
      </head>
      <body style="background-color:#ffffff;font-family:Helvetica,Arial,sans-serif;margin:0;padding:0">
        <table align="center" width="100%" style="max-width:360px;background-color:#ffffff;border:1px solid #eee;border-radius:5px;box-shadow:0 5px 10px rgba(20,50,70,.2);margin:40px auto;padding:30px">
          <tr>
            <td align="center">
              <img
                src="{data.image_url}"
                alt="{data.item_name}"
                width="200"
                style="display:block;margin:0 auto;border:none"
              />
              <p style="color:#0a85ea;font-size:12px;font-weight:bold;text-transform:uppercase;margin:16px 0 4px;">
                Price Drop Alert!
              </p>
              <h2 style="font-size:16px;color:#000;margin:0 0 8px;font-weight:600;text-align:center">
                Your target price for <span style="color:#0a85ea">{data.item_name}</span> has arrived
              </h2>
              <table style="background:#f7f7f7;border-radius:6px;margin:16px auto;width:100%;padding:10px">
                <tr>
                  <td style="text-align:center;font-size:14px;color:#444;">
                    <strong>Previous Price:</strong> ₹{data.prev_price}
                  </td>
                </tr>
                <tr>
                  <td style="text-align:center;font-size:14px;color:#444;">
                    <strong>Current Price:</strong> ₹{data.curr_price}
                  </td>
                </tr>
                <tr>
                  <td style="text-align:center;font-size:14px;color:#d9534f;">
                    <strong>Discount:</strong> {data.change_percent}% OFF
                  </td>
                </tr>
              </table>
              <p style="font-size:14px;color:#444;text-align:center;margin:12px 0;">
                Want to buy now?
                <a href="{data.source_url}" style="color:#0a85ea;text-decoration:underline;" target="_blank">Click here to shop on JioMart</a>
              </p>
            </td>
          </tr>
        </table>
        <p style="font-size:11px;color:#888;text-align:center;margin-top:20px;">This alert was sent to {data.user_email}</p>
      </body>
    </html>
    """
    msg.add_alternative(html_content, subtype='html')

    await aiosmtplib.send(
        msg,
        hostname='smtp.gmail.com',
        port=587,
        username=MAILER_ADDRESS,
        password=MAILER_PASSWORD,
        start_tls=True,
        timeout=20.0,
    )


async def main():
    await send_mail_async(data=MailTemplate(
        user_email="sjts007@gmail.com",
        item_name="Yogabar Protein Muesli 350 g",
        image_url="/images/product/240x240/494231463/yogabar-protein-muesli-350-g-product-images-o494231463-p608274052-0-202403011343.jpg",
        source_url="https://www.jiomart.com/p/groceries/good-life-refined-sunflower-oil-1-l-pouch/491074036",
        prev_price="395",
        curr_price="199",
        change_percent="80"
    ))
