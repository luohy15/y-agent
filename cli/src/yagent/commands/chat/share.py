import os
import asyncio
from typing import Optional
import click

from storage.service import chat as chat_service
from storage.service.user import get_cli_user_id
from yagent.config import config

@click.command()
@click.option('--chat-id', '-c', help='ID of the chat to share')
@click.option('--latest', '-l', is_flag=True, help='Share the latest chat')
@click.option('--message-id', '-m', help='Share up to a specific message ID')
@click.option('--push', '-p', is_flag=True, help='Generate HTML and push to S3 (legacy)')
def share(chat_id: Optional[str], latest: bool, message_id: Optional[str], push: bool):
    """Share a chat conversation.

    Use --latest/-l to share your most recent chat.
    Use --chat-id/-c to share a specific chat ID.
    Use --push/-p to generate HTML and push to S3 (legacy behavior).
    """
    user_id = get_cli_user_id()

    # Handle --latest flag
    if latest:
        chats = asyncio.run(chat_service.list_chats(user_id, limit=1))
        if not chats:
            click.echo("Error: No chats found to share")
            raise click.Abort()
        chat_id = chats[0].chat_id
    elif not chat_id:
        raise click.Abort("Error: Chat ID is required for sharing")

    try:
        if push:
            # Legacy: generate HTML and push to S3
            tmp_file = asyncio.run(chat_service.generate_share_html(chat_id))

            if not config["s3_bucket"] or not config["cloudfront_distribution_id"]:
                click.echo("Error: S3 bucket and CloudFront distribution ID must be configured")
                click.echo("Please set S3_BUCKET and CLOUDFRONT_DISTRIBUTION_ID environment variables")
                raise click.Abort()

            os.system(f'open "{tmp_file}"')
            os.system(f'aws s3 cp "{tmp_file}" s3://{config["s3_bucket"]}/chat/{chat_id}.html > /dev/null')
            os.system(f'aws cloudfront create-invalidation --distribution-id {config["cloudfront_distribution_id"]} --paths "/chat/{chat_id}.html" > /dev/null')
            click.echo(f'https://{config["s3_bucket"]}/chat/{chat_id}.html')
        else:
            # Default: create DB share
            share_id = asyncio.run(chat_service.create_share(user_id, chat_id, message_id))
            click.echo(share_id)

    except ValueError as e:
        click.echo(f"Error: {str(e)}")
        raise click.Abort()
