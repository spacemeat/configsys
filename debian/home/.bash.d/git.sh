# Remembers a merge conflict resolution and automatically stages it the next time it is encountered (during a cherry-pick or rebase, say).
#git config --global rerere.enabled true

# Ignore whitespace, detect moved or copied lines in the same commit, or any commit.
#git alias blam blame -w -C -C -C

# all ignored and untracked files are also stashed and then git clean'd.
#git config --global alias.staash 'stash --all'

# TODO: always rebase on pull

# git config --global alias.foo !foo.sh # runs foo.sh from git

# for using work-specific email, gpg, etc
#[includeif "gitdir:~/src/work/"]
#	path = ~/src/work/.gitconfig
#
#[includeif "gitdir:~/src/oss/"]
#	path = ~/src/oss/.gitconfig



