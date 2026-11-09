if status is-interactive    # interactive conveniences (a `fish -c` gets none, like bash)
    alias setclip "xclip -selection c"
    alias getclip "xclip -selection c -o"
end
