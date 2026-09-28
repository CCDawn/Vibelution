/** Static HTML preview only. No scripts, network, submissions, frames or document navigation. */
export function buildSafeHtmlPreview(content: string): string {
  // Template contents stay inert even before resource attributes are removed.
  const template = document.createElement("template");
  template.innerHTML = content;
  const fragment = template.content;
  fragment.querySelectorAll("script,template,meta,base,link,iframe,frame,frameset,object,embed,portal,svg animate,svg set,svg animateMotion,svg animateTransform").forEach((node) => node.remove());
  for (const element of fragment.querySelectorAll("*")) {
    for (const attribute of [...element.attributes]) {
      const name = attribute.name.toLowerCase();
      if (name.startsWith("on") || ["href", "xlink:href", "src", "srcset", "action", "formaction", "target", "ping", "srcdoc", "autofocus"].includes(name)) {
        // Embedded raster images are useful offline; SVG/data documents stay blocked.
        const embeddedImage = element.tagName === "IMG" && name === "src"
          && /^data:image\/(png|jpeg|gif|webp);base64,[a-z0-9+/=\s]+$/i.test(attribute.value);
        if (!embeddedImage) element.removeAttribute(attribute.name);
      }
    }
  }
  const csp = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'";
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>${template.innerHTML}</body></html>`;
}
