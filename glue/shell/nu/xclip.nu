# xclip: setclip/getclip write/read the X clipboard selection.
def --wrapped setclip [...rest] { ^xclip -selection c ...$rest }
def --wrapped getclip [...rest] { ^xclip -selection c -o ...$rest }
