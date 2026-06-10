# A charmbracelet/vhs script that records a REAL terminal GIF of the DOS
# money-moment by driving the actual `dos` binary.
#
#   1. install vhs:   https://github.com/charmbracelet/vhs   (`brew install vhs`)
#   2. install dos:   pip install -e .        (so `dos` is on PATH)
#   3. record:        vhs examples/demo/verify_demo.tape
#       -> writes docs/assets/verify-money-moment.gif   (a true recorded GIF)
#
# A true-terminal GIF of the `dos verify` money-moment — the live counterpart to the
# examples/demo/verify_visual.html walkthrough and the README hero
# (docs/assets/loop-hero.svg). Use the GIF for surfaces that don't render SVG
# (Twitter/X, LinkedIn, slides); use the SVGs everywhere else.

Output docs/assets/verify-money-moment.gif

Set FontSize 18
Set Width 1200
Set Height 760
Set Theme "Dracula"
Set Padding 24
Set TypingSpeed 45ms

# Land in a throwaway repo so the recording is self-contained.
Hide
Type "cd $(mktemp -d) && dos init . >/dev/null && git init -q && git config user.email d@e.com && git config user.name D && git config commit.gpgsign false" Enter
Type "printf 'def login(): pass\n' > login.py && git add -A && git commit -q -m 'AUTH1: ship the login endpoint'" Enter
Ctrl+L
Show

Sleep 600ms
Type "# an agent says AUTH1 shipped. ask git, not the agent:"  Sleep 700ms  Enter
Type "dos verify AUTH AUTH1"  Sleep 400ms  Enter
Sleep 1800ms

Type "# now it claims AUTH2 is done too — but nothing landed:"  Sleep 700ms  Enter
Type "dos verify AUTH AUTH2"  Sleep 400ms  Enter
Sleep 2600ms
