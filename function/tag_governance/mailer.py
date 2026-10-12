from __future__ import annotations


def send_email(connection_string: str, sender: str, to: list[str], cc: list[str], subject: str, html: str, text: str) -> str:
    from azure.communication.email import EmailClient

    client = EmailClient.from_connection_string(connection_string)
    recipients: dict = {"to": [{"address": a} for a in to]}
    if cc:
        recipients["cc"] = [{"address": a} for a in cc]
    message = {
        "senderAddress": sender,
        "recipients": recipients,
        "content": {"subject": subject, "plainText": text, "html": html},
    }
    result = client.begin_send(message).result()
    return result.get("id", "") if isinstance(result, dict) else str(result)
