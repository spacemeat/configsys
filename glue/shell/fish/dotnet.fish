# .NET: user SDK from dotnet-install.sh (~/.dotnet; no-op when native) + global tools.
if test -d "$HOME/.dotnet"
    set -gx DOTNET_ROOT "$HOME/.dotnet"
    fish_add_path -g "$HOME/.dotnet"
end
test -d "$HOME/.dotnet/tools"; and fish_add_path -ga "$HOME/.dotnet/tools"
