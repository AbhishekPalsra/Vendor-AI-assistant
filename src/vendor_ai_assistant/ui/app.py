"""Role-aware Gradio chat interface for the vendor AI assistant."""

from __future__ import annotations

import os
import logging
import secrets
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

import gradio as gr

from vendor_ai_assistant.chat.answer_generator import (
    SAFE_ERROR_MESSAGE,
    generate_answer,
)
from vendor_ai_assistant.chat.models import ChatSession, UserRole
from vendor_ai_assistant.chat.orchestrator import (
    OrchestrationResult,
    orchestrate_turn,
)
from vendor_ai_assistant.chat.roles import normalize_role
from vendor_ai_assistant.chat.session import (
    create_chat_session,
    list_buyers_for_role,
)


APP_TITLE: Final[str] = "Vendor AI Assistant"
MAX_MESSAGE_LENGTH: Final[int] = 4_000
DEFAULT_SHARE_USERNAME: Final[str] = "vendor-demo"

SessionFactory = Callable[..., ChatSession]
BuyerLoader = Callable[[str], list[dict[str, Any]]]
Orchestrator = Callable[[ChatSession], OrchestrationResult]
AnswerGenerator = Callable[[ChatSession, OrchestrationResult], str]
ChatHistory = list[dict[str, str]]
LOGGER = logging.getLogger(__name__)


def chatbot_history(session: ChatSession | None) -> ChatHistory:
    """Convert trusted session history to Gradio's messages representation."""

    if session is None:
        return []
    return [
        {"role": message.role, "content": message.content}
        for message in session.messages
    ]


def buyer_choices(
    role: str,
    *,
    buyer_loader: BuyerLoader = list_buyers_for_role,
) -> list[tuple[str, str]]:
    """Build readable dropdown labels while retaining buyer IDs as values."""

    normalized = normalize_role(role)
    if normalized == "admin":
        return []
    choices = []
    for buyer in buyer_loader(normalized):
        location = ", ".join(
            value for value in (buyer.get("city"), buyer.get("state")) if value
        )
        tier = buyer.get("retailer_tier")
        details = " · ".join(value for value in (location, tier) if value)
        label = f"{buyer['buyer_name']} — {buyer['buyer_id']}"
        if details:
            label = f"{label} ({details})"
        choices.append((label, str(buyer["buyer_id"])))
    return choices


def begin_role(
    role: str,
    *,
    buyer_loader: BuyerLoader = list_buyers_for_role,
    session_factory: SessionFactory = create_chat_session,
) -> tuple[ChatSession | None, UserRole | None, list[tuple[str, str]]]:
    """Start admin immediately or prepare a verified buyer account selection."""

    normalized = normalize_role(role)
    if normalized == "admin":
        return session_factory("admin"), None, []
    return None, normalized, buyer_choices(normalized, buyer_loader=buyer_loader)


def begin_buyer_session(
    role: str | None,
    buyer_id: str | None,
    *,
    session_factory: SessionFactory = create_chat_session,
) -> ChatSession:
    """Create a customer or retailer session after account verification."""

    if role is None:
        raise ValueError("Choose customer or retailer first.")
    normalized = normalize_role(role)
    if normalized == "admin":
        raise ValueError("Admin sessions do not use the buyer selector.")
    if not isinstance(buyer_id, str) or not buyer_id.strip():
        raise ValueError("Choose an account before starting the chat.")
    return session_factory(normalized, buyer_id=buyer_id.strip())


def submit_message(
    message: str,
    session: ChatSession | None,
    *,
    orchestrator: Orchestrator = orchestrate_turn,
    answer_generator: AnswerGenerator = generate_answer,
) -> tuple[str, ChatHistory, ChatSession | None, str]:
    """Run one complete chat turn and return Gradio-ready state."""

    content = message.strip() if isinstance(message, str) else ""
    if session is None:
        return message, [], None, "Choose a role and start a session first."
    if not content:
        return "", chatbot_history(session), session, "Enter a message to continue."
    if len(content) > MAX_MESSAGE_LENGTH:
        return (
            message,
            chatbot_history(session),
            session,
            f"Messages must be {MAX_MESSAGE_LENGTH:,} characters or fewer.",
        )

    working_session = session.add_message("user", content)
    try:
        orchestration = orchestrator(working_session)
        answer = answer_generator(working_session, orchestration).strip()
        if not answer:
            answer = SAFE_ERROR_MESSAGE
    except Exception:
        LOGGER.exception("Chat turn failed")
        answer = SAFE_ERROR_MESSAGE

    updated_session = working_session.add_message("assistant", answer)
    return (
        "",
        chatbot_history(updated_session),
        updated_session,
        f"Ready · {updated_session.role.title()} session",
    )


def reset_chat() -> tuple[None, None, ChatHistory]:
    """Discard the current browser session and return to role selection."""

    return None, None, []


def _select_role_ui(role: str) -> tuple[Any, ...]:
    try:
        session, pending_role, choices = begin_role(role)
    except Exception:
        return (
            None,
            None,
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(choices=[], value=None),
            "",
            [],
            "The selected role could not be started safely.",
        )

    if session is not None:
        return (
            session,
            None,
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(choices=[], value=None),
            "### Admin chat",
            [],
            "Ready · Admin session",
        )

    return (
        None,
        pending_role,
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(choices=choices, value=None),
        "",
        [],
        f"Choose the {pending_role} account for this demo session.",
    )


def _start_buyer_ui(
    pending_role: str | None,
    buyer_id: str | None,
) -> tuple[Any, ...]:
    try:
        session = begin_buyer_session(pending_role, buyer_id)
    except ValueError as error:
        return (
            None,
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            [],
            str(error),
        )
    except Exception:
        return (
            None,
            gr.update(visible=True),
            gr.update(visible=False),
            "",
            [],
            "The account session could not be started safely.",
        )

    return (
        session,
        gr.update(visible=False),
        gr.update(visible=True),
        f"### {session.role.title()} chat",
        [],
        f"Ready · {session.role.title()} session",
    )


def _new_chat_ui() -> tuple[Any, ...]:
    session, pending_role, history = reset_chat()
    return (
        session,
        pending_role,
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(choices=[], value=None),
        "",
        history,
        "",
        "Choose a role to begin a new chat.",
    )


def build_app() -> gr.Blocks:
    """Create the Gradio component tree without launching a server."""

    with gr.Blocks(title=APP_TITLE, fill_width=False) as demo:
        session_state = gr.State(value=None)
        pending_role_state = gr.State(value=None)

        with gr.Row():
            gr.Markdown(
                "# Vendor AI Assistant\n"
                "Ask about products, availability, pricing, orders, and company guidance."
            )
            new_chat_button = gr.Button("New Chat", variant="secondary", scale=0)

        status = gr.Markdown("Choose a role to begin a new chat.")
        gr.Markdown(
            "_Demo notice: the account selector is not production authentication. "
            "Shared launches are protected by a temporary or configured login._"
        )

        with gr.Group(visible=True) as role_panel:
            gr.Markdown("## Choose your role")
            with gr.Row():
                customer_button = gr.Button("Customer", variant="primary")
                retailer_button = gr.Button("Retailer", variant="primary")
                admin_button = gr.Button("Admin", variant="secondary")

        with gr.Group(visible=False) as account_panel:
            gr.Markdown("## Choose your verified account")
            buyer_dropdown = gr.Dropdown(
                choices=[],
                label="Account",
                interactive=True,
                allow_custom_value=False,
            )
            start_chat_button = gr.Button("Start Chat", variant="primary")

        with gr.Group(visible=False) as chat_panel:
            role_heading = gr.Markdown("")
            chatbot = gr.Chatbot(
                value=[],
                height=520,
                layout="bubble",
                placeholder="Your conversation will appear here.",
            )
            with gr.Row():
                message_box = gr.Textbox(
                    placeholder="Ask the vendor assistant...",
                    show_label=False,
                    max_length=MAX_MESSAGE_LENGTH,
                    autofocus=True,
                    scale=8,
                )
                send_button = gr.Button("Send", variant="primary", scale=1)

        role_outputs = [
            session_state,
            pending_role_state,
            role_panel,
            account_panel,
            chat_panel,
            buyer_dropdown,
            role_heading,
            chatbot,
            status,
        ]
        customer_button.click(
            fn=lambda: _select_role_ui("customer"),
            inputs=None,
            outputs=role_outputs,
            show_progress="hidden",
        )
        retailer_button.click(
            fn=lambda: _select_role_ui("retailer"),
            inputs=None,
            outputs=role_outputs,
            show_progress="hidden",
        )
        admin_button.click(
            fn=lambda: _select_role_ui("admin"),
            inputs=None,
            outputs=role_outputs,
            show_progress="hidden",
        )

        start_chat_button.click(
            fn=_start_buyer_ui,
            inputs=[pending_role_state, buyer_dropdown],
            outputs=[
                session_state,
                account_panel,
                chat_panel,
                role_heading,
                chatbot,
                status,
            ],
            show_progress="hidden",
        )

        chat_outputs = [message_box, chatbot, session_state, status]
        send_button.click(
            fn=submit_message,
            inputs=[message_box, session_state],
            outputs=chat_outputs,
            concurrency_limit=1,
        )
        message_box.submit(
            fn=submit_message,
            inputs=[message_box, session_state],
            outputs=chat_outputs,
            concurrency_limit=1,
        )

        new_chat_button.click(
            fn=_new_chat_ui,
            inputs=None,
            outputs=[
                session_state,
                pending_role_state,
                role_panel,
                account_panel,
                chat_panel,
                buyer_dropdown,
                role_heading,
                chatbot,
                message_box,
                status,
            ],
            show_progress="hidden",
        )

    return demo


def share_auth(
    environment: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Return configured credentials or generate a one-time demo login."""

    values = os.environ if environment is None else environment
    username = values.get("GRADIO_USERNAME", "").strip()
    password = values.get("GRADIO_PASSWORD", "").strip()
    if username and password:
        return username, password
    if username or password:
        raise ValueError(
            "Set both GRADIO_USERNAME and GRADIO_PASSWORD, or leave both unset."
        )

    generated_password = secrets.token_urlsafe(12)
    print(
        "Generated one-time Gradio login: "
        f"username={DEFAULT_SHARE_USERNAME} password={generated_password}"
    )
    return DEFAULT_SHARE_USERNAME, generated_password


def launch_app(demo: gr.Blocks, auth: tuple[str, str]) -> Any:
    """Launch the queued interface through a protected public Gradio share link."""

    return demo.queue(default_concurrency_limit=4).launch(
        share=True,
        auth=auth,
        show_error=False,
    )


def main() -> None:
    launch_app(build_app(), share_auth())


if __name__ == "__main__":
    main()
