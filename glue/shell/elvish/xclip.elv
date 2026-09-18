edit:add-var setclip~ {|@a| xclip -selection c $@a }
edit:add-var getclip~ {|@a| xclip -selection c -o $@a }
