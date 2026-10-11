import type { Link, Root, Text } from "mdast";
import type { Node, Parent } from "unist";

/** Keep Chinese sentence punctuation outside GFM's automatically created links. */
export function remarkConversationAutolinks() {
  return (tree: Root, file: { value: unknown }) => {
    const source = String(file.value);
    const visit = (node: Node) => {
      if (!("children" in node)) return;
      const parent = node as Parent;
      for (let index = 0; index < parent.children.length; index += 1) {
        const child = parent.children[index];
        if (child.type !== "link") {
          visit(child);
          continue;
        }
        const link = child as Link;
        const start = link.position?.start.offset;
        const end = link.position?.end.offset;
        if (start === undefined || end === undefined) continue;
        const raw = source.slice(start, end);
        // Explicit Markdown links and <autolinks> may intentionally contain
        // Chinese paths or punctuation; only repair bare GFM URL detection.
        if (!/^(?:https?:\/\/|www\.)/i.test(raw)) continue;
        if (link.children.length !== 1 || link.children[0].type !== "text") continue;
        const punctuation = raw.search(/[，。；！？、（）【】「」『』]/u);
        if (punctuation < 0) continue;
        const label = raw.slice(0, punctuation);
        if (!label || label === "http://" || label === "https://" || label === "www.") continue;
        link.url = /^www\./i.test(label) ? `http://${label}` : label;
        link.children = [{ type: "text", value: label }];
        const trailing: Text = { type: "text", value: raw.slice(punctuation) };
        parent.children.splice(index + 1, 0, trailing);
        index += 1;
      }
    };
    visit(tree);
  };
}
