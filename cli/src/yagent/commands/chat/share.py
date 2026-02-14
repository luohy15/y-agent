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
@click.option('--push', '-p', is_flag=True, help='Push to S3 after generating HTML')
def share(chat_id: Optional[str], latest: bool, push: bool):
    """Share a chat conversation.

    Use --latest/-l to share your most recent chat.
    Use --chat-id/-c to share a specific chat ID.
    """
    # Handle --latest flag
    if latest:
        chats = asyncio.run(chat_service.list_chats(get_cli_user_id(), limit=1))
        if not chats:
            click.echo("Error: No chats found to share")
            raise click.Abort()
        chat_id = chats[0].chat_id
    elif not chat_id:
        raise click.Abort("Error: Chat ID is required for sharing")

    try:
        # Generate HTML file
        tmp_file = asyncio.run(chat_service.generate_share_html(chat_id))

        if push and (not config["s3_bucket"] or not config["cloudfront_distribution_id"]):
            click.echo("Error: S3 bucket and CloudFront distribution ID must be configured")
            click.echo("Please set S3_BUCKET and CLOUDFRONT_DISTRIBUTION_ID environment variables")
            raise click.Abort()

        # Always open the HTML file
        os.system(f'open "{tmp_file}"')

        if push:
            # Upload to S3
            os.system(f'aws s3 cp "{tmp_file}" s3://{config["s3_bucket"]}/chat/{chat_id}.html > /dev/null')

            # Invalidate CloudFront cache
            os.system(f'aws cloudfront create-invalidation --distribution-id {config["cloudfront_distribution_id"]} --paths "/chat/{chat_id}.html" > /dev/null')

            # Print the shareable URL
            click.echo(f'https://{config["s3_bucket"]}/chat/{chat_id}.html')

    except ValueError as e:
        click.echo(f"Error: {str(e)}")
        raise click.Abort()
