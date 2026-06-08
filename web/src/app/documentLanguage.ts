import type { Language } from "../i18n/shellDictionary";

type DocumentLanguageTarget = Pick<Document, "body" | "documentElement">;

function markAsApplicationChrome(element: HTMLElement): void {
  element.translate = false;
  element.setAttribute("translate", "no");
  element.classList.add("notranslate");
}

export function applyWorkbenchDocumentLanguage(targetDocument: DocumentLanguageTarget, lang: Language): void {
  targetDocument.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  markAsApplicationChrome(targetDocument.documentElement);

  if (targetDocument.body) {
    markAsApplicationChrome(targetDocument.body);
  }
}
