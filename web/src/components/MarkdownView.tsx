import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { OutgoingWikiLinkDto } from "../api/types";

interface Props {
  markdown: string;
  outgoing: OutgoingWikiLinkDto[];
  onOpen: (key: string, label: string) => void;
}

const WIKI = /\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]/g;

/** Turns [[Target#Heading|Alias]] into markdown links with a `wiki:` URL we handle on click. */
export function wikiToLinks(md: string): string {
  return md.replace(WIKI, (_m, target: string, anchor: string | undefined, alias: string | undefined) => {
    const text = (alias ?? (anchor ? `${target} › ${anchor}` : target)).replace(/[[\]]/g, "");
    return `[${text}](wiki:${encodeURIComponent(target.trim())})`;
  });
}

const urlTransform = (url: string) => (url.startsWith("wiki:") ? url : defaultUrlTransform(url));

/** DV-1 rendered Markdown; wikilinks travel inside Atlas, unresolved ones open the ghost node. */
export function MarkdownView({ markdown, outgoing, onOpen }: Props) {
  const resolve = (target: string) => {
    const t = target.toLowerCase();
    return outgoing.find((o) => o.target_name.toLowerCase() === t);
  };
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={urlTransform}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("wiki:")) {
              const target = decodeURIComponent(href.slice(5));
              const link = resolve(target);
              const resolved = link?.resolved;
              return (
                <a
                  href={resolved ? `#doc-${resolved.id}` : `#ghost-${encodeURIComponent(target)}`}
                  className={resolved ? "wikilink" : "wikilink is-ghost"}
                  title={resolved ? resolved.path : "This note does not exist yet"}
                  onClick={(e) => {
                    e.preventDefault();
                    if (resolved) onOpen(`doc:${resolved.id}`, resolved.title);
                    else onOpen(`ghost:${link?.target_name ?? target}`, target);
                  }}
                >
                  {children}
                </a>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            );
          },
          img: ({ alt }) => <span className="muted">[image{alt ? `: ${alt}` : ""}]</span>,
        }}
      >
        {wikiToLinks(markdown)}
      </ReactMarkdown>
    </div>
  );
}
