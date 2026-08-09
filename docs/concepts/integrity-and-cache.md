# Integrity and cache

The transport contract is status check, temporary file, complete stream, optional published-digest
check, then atomic rename. A partial response never occupies the final cache path.

The cache key is coordinate plus artifact role:

```text
$MOLHUB_HOME/files/<kind>/<namespace>/<name>@<version>/<role>
```

This is not a content-addressed store. The coordinate already names the version, including sources
whose platform publishes no digest. Python and Node deliberately share this layout.
