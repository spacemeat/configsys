# tree-sitter-cli: alias to the configsys-managed binary. No-op where native on PATH.
use path
var loc = (cs-loc tree-sitter-cli)
if (and (not-eq $loc '') (path:is-regular $loc/tree-sitter)) {
  edit:add-var tree-sitter~ {|@a| (external $loc/tree-sitter) $@a }
}
