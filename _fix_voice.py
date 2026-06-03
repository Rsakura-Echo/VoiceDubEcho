#!/usr/bin/env python3
"""Fix the voice picker forEach block - remove toggleAudio, use data attrs."""
with open('frontend/js/components.js', 'r', encoding='utf-8') as f:
    lines = f.readlines()

out = []
skip = 0
for i, line in enumerate(lines):
    if skip > 0:
        skip -= 1
        continue

    # Detect the start of the broken voice forEach block
    if "// Voice list" in line:
        out.append(line)
        # Find the opening of else block
        continue

    if 'html += ' in line and 'style="max-height:260px;overflow-y:auto"' in line:
        out.append(line)
        continue

    if 'voices.forEach(v => {' in line and i > 300:
        sp_line = '          var sp = (v.audio_path || "").replace(/\\\\/g, "/");\n'

        div_line = (
            "          html += '<div style=\"display:flex;align-items:center;"
            "justify-content:space-between;padding:10px 12px;border:1px solid var(--border);"
            "border-radius:6px;margin-bottom:6px;cursor:pointer\" "
            "data-vpath=\"' + sp + '\" data-vid=\"' + v.id + '\" "
            "onclick=\"Components._pickVoice(this.dataset.vpath,this.dataset.vid)\">';\n"
        )
        name_line = "          html += '<div><strong style=\"font-size:13px\">' + this._esc(v.name) + '</strong></div>';\n"
        close_line = "          html += '</div>';\n"
        end_line = "        });\n"

        out.append(sp_line)
        out.append(div_line)
        out.append(name_line)
        out.append(close_line)
        out.append(end_line)
        skip = 7  # skip the old 7 lines
    else:
        out.append(line)

with open('frontend/js/components.js', 'w', encoding='utf-8') as f:
    f.writelines(out)
print("Done")
