# syntax=docker/dockerfile:1.7

# Existing production data was initialized with glibc collation metadata.
# Keep PostgreSQL on Debian/bookworm instead of Alpine/musl so the recorded
# collation version can be checked by PostgreSQL at connection time.
FROM postgres:16.14-bookworm
