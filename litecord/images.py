"""

Litecord
Copyright (C) 2018-2021  Luna Mendes and Litecord Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

import os
import mimetypes
import asyncio
import base64
import tempfile
from typing import Optional, Tuple, Union

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from io import BytesIO

from logbook import Logger
from PIL import Image


IMAGE_FOLDER = Path("./images")
log = Logger(__name__)


EXTENSIONS = {"image/jpeg": "jpeg", "image/webp": "webp"}


MIMES = {
    "jpg": "image/jpeg",
    "jpe": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}

STATIC_IMAGE_MIMES = ["image/png", "image/jpeg", "image/webp"]


def get_ext(mime: str) -> str:
    if mime in EXTENSIONS:
        return EXTENSIONS[mime]

    extensions = mimetypes.guess_all_extensions(mime)
    return extensions[0].strip(".")


def get_mime(ext: str):
    if ext in MIMES:
        return MIMES[ext]

    return mimetypes.types_map[f".{ext or 'webp'}"]


@dataclass
class Icon:
    """Main icon class"""

    key: Optional[str]
    icon_hash: Optional[str]
    mime: Optional[str]

    @property
    def fs_hash(self) -> Optional[str]:
        icon_hash = self.icon_hash
        return icon_hash.split(".")[-1] if icon_hash and "." in icon_hash else icon_hash

    @property
    def as_path(self) -> Optional[str]:
        """Return a filesystem path for the given icon."""
        if self.mime is None:
            return None

        ext = get_ext(self.mime)
        return str(IMAGE_FOLDER / f"{self.fs_hash if self.icon_hash else self.key}.{ext}")

    @property
    def as_pathlib(self) -> Optional[Path]:
        """Get a Path instance of this icon."""
        if self.as_path is None:
            return None

        return Path(self.as_path)

    @property
    def extension(self) -> Optional[str]:
        """Get the extension of this icon."""
        if self.mime is None:
            return None

        return get_ext(self.mime)

    def __bool__(self):
        return bool(self.key and self.icon_hash and self.mime)


class ImageError(Exception):
    """Image error class."""

    pass


def to_raw(data_type: str, data: str) -> Optional[bytes]:
    """Given a data type in the data URI and data,
    give the raw bytes being encoded."""
    if data_type == "base64":
        return base64.b64decode(data)

    return None


def _calculate_hash(fhandler) -> str:
    """Generate a hash of the given file.

    This calls the seek(0) of the file handler
    so it can be reused.

    Parameters
    ----------
    fhandler: file object
        Any file-like object.

    Returns
    -------
    str
        The SHA256 hash of the given file.
    """
    hash_obj = sha256()

    for chunk in iter(lambda: fhandler.read(4096), b""):
        hash_obj.update(chunk)

    # so that we can reuse the same handler
    # later on
    fhandler.seek(0)

    return hash_obj.hexdigest()


async def calculate_hash(fhandle, loop=None) -> str:
    """Calculate a hash of the given file handle.

    Uses run_in_executor to do the job asynchronously so
    the application doesn't lock up on large files.
    """
    if not loop:
        loop = asyncio.get_event_loop()

    fut = loop.run_in_executor(None, _calculate_hash, fhandle)
    return await fut


def parse_data_uri(string) -> tuple:
    """Extract image data."""
    try:
        header, headered_data = string.split(";")

        _, given_mime = header.split(":")
        data_type, data = headered_data.split(",")

        raw_data = to_raw(data_type, data)
        if raw_data is None:
            raise ImageError("Unknown data header")
        if raw_data.startswith(b'\x89\x50\x4E\x47\x0D\x0A\x1A\x0A'):
            given_mime = "image/png"
        elif raw_data[0:3] == b"\xff\xd8\xff" or raw_data[6:10] in (b"JFIF", b"Exif"):
            given_mime = "image/jpeg"
        elif raw_data.startswith((b"\x47\x49\x46\x38\x37\x61", b"\x47\x49\x46\x38\x39\x61")):
            given_mime = "image/gif"
        elif raw_data.startswith(b"RIFF") and raw_data[8:12] == b"WEBP":
            given_mime = "image/webp"
        elif given_mime == "application/octet-stream":
            raise ImageError("Unknown data header")

        return given_mime, raw_data
    except ValueError:
        raise ImageError("Unknown data header")


def _get_args(scope: str) -> Tuple[str, str]:
    fields = {
        "member_avatar": "avatar",
        "member_banner": "banner",
        "user_avatar": "avatar",
        "user_avatar_decoration": "avatar_decoration",
        "user_banner": "banner",
        "guild_icon": "icon",
        "guild_splash": "splash",
        "guild_discovery_splash": "discovery_splash",
        "guild_banner": "banner",
        "channel_icon": "icon",
        "channel_banner": "banner",
    }

    tables = {
        "member_avatar": "members",
        "member_banner": "members",
        "user_avatar": "users",
        "user_avatar_decoration": "users",
        "user_banner": "users",
        "guild_icon": "guilds",
        "guild_splash": "guilds",
        "guild_discovery_splash": "guilds",
        "guild_banner": "guilds",
        "channel_icon": "group_dm_channels",
        "channel_banner": "guild_channels",
    }
    return fields[scope], tables[scope]


def _invalid(kwargs: dict) -> Optional[Icon]:
    """Send an invalid value."""
    # TODO: remove optinality off this (really badly designed):
    #  - also remove kwargs off this function
    #  - also make an Icon.empty() constructor, and remove need for this entirely
    if not kwargs.get("always_icon", False):
        return None

    return Icon(None, None, "")


def try_unlink(path: Union[Path, str]):
    """Try unlinking a file. Does not do anything if the file
    does not exist."""
    try:
        if isinstance(path, Path):
            path.unlink()
        else:
            os.remove(path)
    except FileNotFoundError:
        pass


async def resize_gif(raw_data: bytes, target: tuple) -> tuple:
    """Resize a GIF image."""
    # generate a temporary file to call gifsticle to and from.
    input_fd, input_path = tempfile.mkstemp(suffix=".gif")
    _, output_path = tempfile.mkstemp(suffix=".gif")

    input_handler = os.fdopen(input_fd, "wb")

    # make sure its valid image data
    data_fd = BytesIO(raw_data)
    image = Image.open(data_fd)
    image.close()

    log.info("resizing a GIF from {} to {}", image.size, target)

    # insert image info on input_handler
    # close it to make it ready for consumption by gifsicle
    input_handler.write(raw_data)
    input_handler.close()

    # call gifsicle under subprocess
    log.debug("input: {}", input_path)
    log.debug("output: {}", output_path)

    process = await asyncio.create_subprocess_shell(
        f"gifsicle --resize {target[0]}x{target[1]} " f"{input_path} > {output_path}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # run it, etc.
    out, err = await process.communicate()

    log.debug("out + err from gifsicle: {}", out + err)

    # write over an empty data_fd
    data_fd = BytesIO()
    output_handler = open(output_path, "rb")
    data_fd.write(output_handler.read())

    # close unused handlers
    output_handler.close()

    # delete the files we created with mkstemp
    try_unlink(input_path)
    try_unlink(output_path)

    # reseek, save to raw_data, reseek again.
    # TODO: remove raw_data altogether as its inefficient
    # to have two representations of the same bytes
    data_fd.seek(0)
    raw_data = data_fd.read()
    data_fd.seek(0)

    return data_fd, raw_data


class IconManager:
    """Main icon manager."""

    def __init__(self, app):
        self.app = app
        self.storage = app.storage

    async def _convert_ext(self, icon: Icon, target: str):
        target = "jpeg" if target == "jpg" else target

        target_mime = get_mime(target)
        log.info("converting from {} to {}", icon.mime, target_mime)

        target_path = IMAGE_FOLDER / f"{icon.fs_hash if icon.fs_hash else icon.key}.{target}"

        if target_path.exists():
            return Icon(icon.key, icon.icon_hash, target_mime)

        image = Image.open(icon.as_path)
        target_fd = target_path.open("wb")

        if target == "jpeg":
            image = image.convert("RGB")

        image.save(target_fd, format=target)
        target_fd.close()

        return Icon(icon.key, icon.icon_hash, target_mime)

    async def generic_get(self, scope, key, icon_hash, **kwargs) -> Optional[Icon]:
        """Get any icon."""

        log.debug("GET {} {} {}", scope, key, icon_hash)
        key = str(key)

        hash_query = "AND hash = $3" if icon_hash else ""

        # hacky solution to only add icon_hash
        # when needed.
        args = [scope, key]

        if icon_hash:
            args.append(icon_hash)

        icon_row = await self.storage.db.fetchrow(
            f"""
        SELECT key, hash, mime
        FROM icons
        WHERE scope = $1
          AND key = $2
          {hash_query}
        """,
            *args,
        )

        if icon_row is None:
            return None

        icon = Icon(icon_row["key"], icon_row["hash"], icon_row["mime"])

        # ensure we aren't messing with NULLs everywhere.
        if icon.as_pathlib is None:
            return None

        if not icon.as_pathlib.exists():
            await self.delete(icon)
            return None

        if icon.extension is None:
            return None

        if "ext" in kwargs and kwargs["ext"] != icon.extension:
            return await self._convert_ext(icon, kwargs["ext"])

        return icon

    async def get_guild_icon(self, guild_id: int, icon_hash: str, **kwargs):
        """Get an icon for a guild."""
        return await self.generic_get("guild", guild_id, icon_hash, **kwargs)

    async def put(self, scope: str, key: str, b64_data: str, **kwargs) -> Icon:
        """Insert an icon."""
        if not b64_data:
            return _invalid(kwargs)

        mime, raw_data = parse_data_uri(b64_data)
        if mime not in ("image/png", "image/jpeg", "image/gif", "image/webp"):
            return _invalid(kwargs)

        # TODO: filter mimes
        data_fd = BytesIO(raw_data)

        # get an extension for the given data uri
        extension = get_ext(mime)

        # size management is different for gif files
        # as they're composed of multiple frames.
        if "size" in kwargs and mime == "image/gif":
            data_fd, raw_data = await resize_gif(raw_data, kwargs["size"])
        elif "size" in kwargs:
            image = Image.open(data_fd)

            if mime == "image/jpeg":
                image = image.convert("RGB")

            want = kwargs["size"]

            log.info("resizing from {} to {}", image.size, want)

            image.thumbnail(want, resample=Image.LANCZOS)

            data_fd = BytesIO()
            image.save(data_fd, format=extension)

            # reseek to copy it to raw_data
            data_fd.seek(0)
            raw_data = data_fd.read()

            data_fd.seek(0)

        # calculate sha256
        # ignore icon hashes if we're talking about emoji
        icon_hash = (hex(hash(scope)).lstrip("-0x")[:3] + hex(hash(key)).lstrip("-0x")[:3] + "." + await calculate_hash(data_fd)) if scope != "emoji" else None

        if mime == "image/gif" and scope != "emoji":
            icon_hash = f"a_{icon_hash}"

        log.debug("PUT icon {!r} {!r} {!r} {!r}", scope, key, icon_hash, mime)

        await self.storage.db.execute(
            """
        INSERT INTO icons (scope, key, hash, mime)
        VALUES ($1, $2, $3, $4)
        """,
            scope,
            str(key),
            icon_hash,
            mime,
        )

        # write it off to fs
        icon_path = IMAGE_FOLDER / f"{icon_hash.split('.')[-1] if icon_hash else key}.{extension}"
        if not icon_path.exists():
            icon_path.write_bytes(raw_data)

        # copy from data_fd to icon_fd
        # with icon_path.open(mode='wb') as icon_fd:
        #    icon_fd.write(data_fd.read())

        return Icon(str(key), icon_hash, mime)

    async def delete(self, icon: Icon):
        """Delete an icon from the database and filesystem."""
        if not icon:
            return

        log.debug("DEL {}", icon)

        await self.storage.db.execute(
            """
        DELETE FROM icons
        WHERE STRPOS (hash, $1) > 0
        """,
            icon.fs_hash,
        )

        paths = IMAGE_FOLDER.glob(f"{icon.fs_hash if icon.fs_hash else icon.key}.*")

        for path in paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    async def update(self, scope: str, key: str, new_icon_data: str, **kwargs) -> Icon:
        """Update an icon on a key."""
        arg, table = _get_args(scope)
        query = f"SELECT {arg} from {table} "
        if "_" in str(key):  # Support guild_user
            query += "WHERE user_id = $1 and guild_id = $2"
            args = (int(key.split('_')[1]), int(key.split('_')[0]))
        else:
            query += "WHERE id = $1"
            args = (key,)

        old_icon_hash = await self.storage.db.fetchval(query, *args)

        # converting key to str only here since from here onwards
        # its operations on the icons table (or a dereference with
        # the delete() method but that will work regardless)
        key = str(key)
        old_icon = await self.generic_get(scope, key, old_icon_hash)

        try:
            icon = await self.put(scope, key, new_icon_data, **kwargs)
        except Exception:
            return old_icon or _invalid(kwargs)

        if old_icon and old_icon.fs_hash != icon.fs_hash:
            hits = await self.storage.db.fetch(
                """
            SELECT hash
            FROM icons
            WHERE STRPOS (hash, $1) > 0
            """,
                old_icon.fs_hash,
            )
            if hits and len(hits) <= 1:  # if we have more than one hit, we can't delete it
                await self.delete(old_icon)

        return icon
