# .NET: user SDK (~/.dotnet; no-op when native) + global tools.
use path
if (path:is-dir $E:HOME/.dotnet) {
  set-env DOTNET_ROOT $E:HOME/.dotnet
  if (not (has-value $paths $E:HOME/.dotnet)) { set paths = [$E:HOME/.dotnet $@paths] }
}
if (and (path:is-dir $E:HOME/.dotnet/tools) (not (has-value $paths $E:HOME/.dotnet/tools))) { set paths = [$@paths $E:HOME/.dotnet/tools] }
