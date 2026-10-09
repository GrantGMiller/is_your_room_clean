from flask_tools import SendEmail_SMTP

import config


def send_email(**kwargs):
    SendEmail_SMTP(
        **kwargs,
        #
        frm=config.ADMINS[0],
        smtpServerURL=config.SES_SMTP_SERVER,
        smtpUsername=config.SES_USERNAME,
        smtpPassword=config.SES_PASSWORD,
    )
