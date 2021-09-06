"""

Litecord
Copyright (C) 2018-2019  Luna Mendes

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

import pytest
from litecord.common.guilds import add_member

pytestmark = pytest.mark.asyncio


async def test_channel_create(test_cli_user):
    guild = await test_cli_user.create_guild()

    # guild test object teardown should destroy the channel as well!
    resp = await test_cli_user.post(
        f"/api/v6/guilds/{guild.id}/channels",
        json={
            "name": "hello-world",
        },
    )
    assert resp.status_code == 200
    rjson = await resp.json
    assert rjson["name"] == "hello-world"

    refetched_guild = await guild.refetch()
    assert len(refetched_guild.channels) == 2


async def test_channel_message_send(test_cli_user):
    guild = await test_cli_user.create_guild()
    channel = guild.channels[0]
    resp = await test_cli_user.post(
        f'/api/v6/channels/{channel["id"]}/messages',
        json={
            "content": "hello world",
        },
    )
    assert resp.status_code == 200
    rjson = await resp.json
    assert rjson["content"] == "hello world"


async def test_channel_message_send_on_new_channel(test_cli_user):
    guild = await test_cli_user.create_guild()
    channel = await test_cli_user.create_guild_channel(guild_id=guild.id)
    assert channel.guild_id == guild.id

    refetched_guild = await guild.refetch()
    assert len(refetched_guild.channels) == 2

    resp = await test_cli_user.post(
        f"/api/v6/channels/{channel.id}/messages",
        json={
            "content": "hello world",
        },
    )
    assert resp.status_code == 200
    rjson = await resp.json
    assert rjson["content"] == "hello world"


async def test_channel_message_delete(test_cli_user):
    guild = await test_cli_user.create_guild()
    channel = await test_cli_user.create_guild_channel(guild_id=guild.id)
    message = await test_cli_user.create_message(
        guild_id=guild.id, channel_id=channel.id
    )

    resp = await test_cli_user.delete(
        f"/api/v6/channels/{channel.id}/messages/{message.id}",
    )
    assert resp.status_code == 204


async def test_channel_message_delete_different_author(test_cli_user):
    guild = await test_cli_user.create_guild()
    channel = await test_cli_user.create_guild_channel(guild_id=guild.id)
    user = await test_cli_user.create_user()
    async with test_cli_user.app.app_context():
        await add_member(guild.id, user.id)

    message = await test_cli_user.create_message(
        guild_id=guild.id, channel_id=channel.id, author_id=user.id
    )

    resp = await test_cli_user.delete(
        f"/api/v6/channels/{channel.id}/messages/{message.id}",
        headers={"authorization": user.token},
    )
    assert resp.status_code == 204
