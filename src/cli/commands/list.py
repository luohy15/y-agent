from typing import Optional
import click
import shutil
from tabulate import tabulate

from chat.app import ChatApp

def get_column_widths():
    # Column weights (higher number = wider column)
    weights = {
        "ID": 1,        
        "Created": 2,   
        "Title": 5,     
        "Context": 8,   
        "Model": 2,     
        "Provider": 2   
    }
    
    # Calculate total weight
    total_weight = sum(weights.values())
    
    # Get terminal width and reserve space for borders/padding
    terminal_width = shutil.get_terminal_size().columns
    available_width = terminal_width - 10
    
    # Calculate widths proportionally based on weights
    widths = [max(3, int(available_width * weight / total_weight)) for weight in weights.values()]
    return widths

@click.command('list')
@click.option('--keyword', '-k', help='Filter chats by message content')
@click.option('--model', '-m', help='Filter chats by model name')
@click.option('--provider', '-p', help='Filter chats by provider name')
@click.option('--limit', '-l', default=10, help='Maximum number of chats to show (default: 10)')
@click.option('--verbose', '-v', is_flag=True, help='Show detailed information')
def list_chats(keyword: Optional[str], model: Optional[str], provider: Optional[str], limit: int, verbose: bool = False):
    """List chat conversations with optional filtering.

    Shows chats sorted by creation time (newest first).
    Use --keyword to filter by message content.
    Use --model to filter by model name.
    Use --provider to filter by provider name.
    Use --limit to control the number of results.
    """
    from config import config
    if verbose:
        click.echo(f"{click.style('Chat data will be stored in:', fg='green')}\n{click.style(config['chat_file'], fg='cyan')}")
        if any([keyword, model, provider]):
            filters = []
            if keyword:
                filters.append(f"keyword: '{keyword}'")
            if model:
                filters.append(f"model: '{model}'")
            if provider:
                filters.append(f"provider: '{provider}'")
            click.echo(f"Applied filters: {', '.join(filters)}")
        click.echo(f"Result limit: {limit}")
    chat_app = ChatApp()
    chats = chat_app.chat_manager.service.list_chats(
        keyword=keyword,
        model=model,
        provider=provider,
        limit=limit
    )
    if not chats:
        if any([keyword, model, provider]):
            filters = []
            if keyword:
                filters.append(f"keyword '{keyword}'")
            if model:
                filters.append(f"model '{model}'")
            if provider:
                filters.append(f"provider '{provider}'")
            click.echo(f"No chats found matching filters: {', '.join(filters)}")
        else:
            click.echo("No chats found")
        return

    if verbose:
        click.echo(f"Found {len(chats)} chat(s)")

    # Get dynamic column widths
    widths = get_column_widths()
    
    # Prepare table data
    table_data = []
    for chat in chats:
        # Get title from first message if available
        if chat.messages:
            title = chat.messages[0].content[:widths[2]]  # Use Title column width
            if len(chat.messages[0].content) > widths[2]:
                title += "..."
        else:
            title = "No messages"

        # Get full context by joining all message contents
        # Limit each message content based on available width
        msg_width = widths[3] // len(chat.messages) if chat.messages else widths[3]
        messages = []
        for m in chat.messages:
            content = m.content[:msg_width]
            if len(m.content) > msg_width:
                content += "..."
            messages.append(f"{m.role}: {content}")
        full_context = " | ".join(messages)
        if len(full_context) > widths[3]:
            full_context = full_context[:widths[3]-3] + "..."

        # Get provider and model from last assistant message if available
        model = "N/A"
        provider = "N/A"
        # Search messages in reverse to find the last assistant message
        for msg in reversed(chat.messages):
            if msg.role == "assistant":
                if msg.model:
                    model = msg.model[:widths[4]]  # Use Model column width
                if msg.provider:
                    provider = msg.provider[:widths[5]]  # Use Provider column width
                break

        table_data.append([
            chat.id,
            f"{chat.create_time.split('T')[0]} {chat.create_time.split('T')[1][:5]}",
            title,
            full_context,
            model,
            provider
        ])

    # Print formatted table
    headers = ["ID", "Created", "Title", "Context", "Model", "Provider"]
    click.echo(tabulate(
        table_data,
        headers=headers,
        tablefmt="simple",
        maxcolwidths=widths,
        numalign='left',
        stralign='left'
    ))
