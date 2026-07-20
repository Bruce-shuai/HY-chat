export const ADMIN_CONTACT_TEXT =
  "如果权限不够，你可以咨询管理员（微信：Hy_284970670）。";

export function appendAdminContact(message: string) {
  if (message.includes("Hy_284970670")) return message;
  return `${message}\n\n${ADMIN_CONTACT_TEXT}`;
}
