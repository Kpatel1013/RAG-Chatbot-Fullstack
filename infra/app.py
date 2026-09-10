#!/usr/bin/env python3

import aws_cdk as cdk

from rag_chatbot.stack import RagChatbotStack

app = cdk.App()

RagChatbotStack(
    app,
    "RagChatbotStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
)

app.synth()
