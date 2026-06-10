# HTML → LaTeX conversion spec (implemented by `paper/assemble_arxiv.py`)

These are the rules the generator (`paper/assemble_arxiv.py`) applies to turn
`paper/sections/NN_*.html` → `paper/arxiv/sections/NN_*.tex`, deterministically, on every
`python paper/build.py`. Faithful rendering: presentation only, NEVER a number, a word, or
a claim changes. **This is a spec for the CODE, not a manual checklist — the `.tex` are
generated, so do not hand-port a section.** Edit the rules here + the converter when the
source grows a construct the generator does not yet handle (the converter is small and
readable); then the whole paper regenerates. Kept also as the human-readable contract for
what the LaTeX rendering is allowed to do.

## Inline substitutions (apply everywhere)
| HTML | LaTeX |
|---|---|
| `&ldquo;` `&rdquo;` | `` `` `` / `''` |
| `&lsquo;` `&rsquo;` | `` ` `` / `'` (apostrophes: `it's` → `it's`) |
| `&mdash;` | `---` |
| `&ndash;` | `--` |
| `&minus;` | `$-$` |
| `&nbsp;` | `~` |
| `&sect;` | `\S` |
| `&times;` | `$\times$` |
| `&rarr;` | `$\rightarrow$` |
| `&hellip;` or `…` | `\dots` |
| `&amp;` | `\&` |
| literal `%` | `\%` |
| literal `&` | `\&` |
| literal `_` (in prose/code) | `\_` |
| literal `#` `$` | `\#` `\$` |
| `~N` meaning approx | `$\sim$N` |
| `<em>x</em>` | `\emph{x}` |
| `<strong>x</strong>` | `\textbf{x}` |
| `<code>x</code>` | `\code{x}` (defined in main.tex = \texttt; remember to escape `_` `#` etc. INSIDE it) |
| `<sub>x</sub>` `<sup>x</sup>` | `$_{x}$` `$^{x}$` |

`\J` is a macro for the bold payoff symbol **J** (defined in main.tex). Use `$\J = 10$`
for "J = 10". Use `\byteclean` only if you like; plain `\textbf{byte-clean}` is fine too.

## Block structure
- `<h2 data-sec="foo">Bar</h2>` → `\section{Bar}\label{sec:foo}`
- `<h3 data-sec="foo.bar">Baz</h3>` → `\subsection{Baz}\label{sec:foo-bar}` (DOT → HYPHEN in the label)
- `<h3>` / `<h4>` with no anchor → `\subsection{...}` / `\subsubsection{...}`
- `<p>...</p>` → a paragraph (blank line before/after; drop the tags)
- `<ul><li>..</li></ul>` → `\begin{itemize}\item ..\end{itemize}`
- `<ol><li>..</li></ol>` → `\begin{enumerate}\item ..\end{enumerate}`
- `<blockquote>..</blockquote>` → `\begin{quote}..\end{quote}`

## Cross-references (the `{{...}}` placeholders)
Replace EVERY `{{kind:name}}` with `\cref{kind:name}`, converting any DOT in `name`
to a HYPHEN. Examples:
- `{{sec:payoff}}` → `\cref{sec:payoff}`
- `{{sec:payoff.race}}` → `\cref{sec:payoff-race}`
- `{{fig:hero}}` → `\cref{fig:hero}`
- `{{tbl:detectors}}` → `\cref{tab:detectors}`  ← NOTE: table labels use prefix **tab:** not tbl:
- `{{fact:spend_writeadmit}}` → `\cref{fact:spend_writeadmit}` (keep underscore in label; it's fine in \label/\cref)
Where the HTML literally writes "Figure&nbsp;{{fig:x}}" / "Table&nbsp;{{tbl:x}}" /
"&sect;{{sec:x}}", replace the WHOLE thing (the word + placeholder) with just `\cref{...}`
(cleveref prints "Figure 3" / "Table 2" / "section 4" itself). E.g.
`Figure&nbsp;{{fig:pipeline}}, &sect;{{sec:bench}}` → `\cref{fig:pipeline}, \cref{sec:bench}`.

## Figures
```
<figure data-fig="X"> <img src="figs/Y.png" alt="..."> <figcaption>Z</figcaption> </figure>
```
→
```
\begin{figure}[t]
  \centering
  \includegraphics[width=\linewidth]{Y}
  \caption{Z}
  \label{fig:X}
\end{figure}
```
- If the `<figure>` has `class="wide"` → use `figure*` and `width=\textwidth`.
- DROP the `alt=` text (it's accessibility text, not caption). Keep only `<figcaption>` as `\caption{}`.
- The image basename `Y` is referenced WITHOUT the `figs/` path and WITHOUT `.png`
  (main.tex sets `\graphicspath{{../figs/}}`). If the referenced PNG name differs from
  what exists in `paper/figs/`, use the name that EXISTS in `paper/figs/` (ls it) and
  note the substitution in your report.
- A `<figcaption>` that starts "Figure&nbsp;{{fig:X}}. ..." — DROP the leading
  "Figure N." (LaTeX adds it); keep the caption text after it.

## Tables
Convert `<table>` to `booktabs` style:
```
\begin{table}[t]
  \centering
  \caption{<caption text if any, else omit>}
  \label{tab:NAME}
  \begin{tabular}{l l r}   % choose column spec: l for text, r for numbers, c to center
    \toprule
    Head A & Head B & Head C \\
    \midrule
    a & b & c \\
    ...
    \bottomrule
  \end{tabular}
\end{table}
```
- `<thead>` row → header row + `\midrule` after it. `<tbody>` rows → body. Cells split on `<td>`/`<th>`, joined with ` & `, each row ends ` \\`.
- A `data-tbl="X"` anchor → `\label{tab:X}`.
- If a table is wide, you MAY use `\small` / `\footnotesize` before `\begin{tabular}` or wrap in `\resizebox{\textwidth}{!}{...}`. Prefer readability.
- Escape `%`, `&`, `_` inside cells.

## Hard rules
- Balanced braces and balanced environments. Every `\begin` has its `\end`.
- Do NOT invent content. Do NOT drop any sentence, number, footnote, or list item.
- Preserve emphasis exactly (every `<em>`/`<strong>`).
- Keep the prose verbatim modulo the entity/tag substitutions above.
- Output ONLY the section body (\section... down). NO `\documentclass`, NO `\begin{document}`
  — these files are `\input{}` into main.tex.
- If you hit something the spec doesn't cover, choose the minimal clean LaTeX and note it.
