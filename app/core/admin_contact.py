ADMIN_CONTACT_TEXT = "如果权限不够，你可以咨询管理员（微信：Hy_284970670）。"


def append_admin_contact(message: str) -> str:
    if "Hy_284970670" in message:
        return message
    return f"{message}\n\n{ADMIN_CONTACT_TEXT}"
