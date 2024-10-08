import uuid
import chainlit as cl
from orchestrator import MultiAgentOrchestrator, OrchestratorConfig, BedrockClassifier, BedrockClassifierOptions
from agents import create_tech_agent, create_travel_agent, create_health_agent
from multi_agent_orchestrator.types import ConversationMessage


# Initialize the orchestrator
custom_bedrock_classifier = BedrockClassifier(BedrockClassifierOptions(
    model_id='anthropic.claude-3-haiku-20240307-v1:0',
    inference_config={
        'maxTokens': 500,
        'temperature': 0.7,
        'topP': 0.9
    }
))

orchestrator = MultiAgentOrchestrator(options=OrchestratorConfig(
    LOG_AGENT_CHAT=True,
    LOG_CLASSIFIER_CHAT=True,
    LOG_CLASSIFIER_RAW_OUTPUT=True,
    LOG_CLASSIFIER_OUTPUT=True,
    LOG_EXECUTION_TIMES=True,
    MAX_RETRIES=3,
    USE_DEFAULT_AGENT_IF_NONE_IDENTIFIED=True,
    MAX_MESSAGE_PAIRS_PER_AGENT=10
), classifier=custom_bedrock_classifier)

# Add agents to the orchestrator
orchestrator.add_agent(create_tech_agent())
orchestrator.add_agent(create_travel_agent())
orchestrator.add_agent(create_health_agent())

@cl.on_chat_start
async def start():
    cl.user_session.set("user_id", str(uuid.uuid4()))
    cl.user_session.set("session_id", str(uuid.uuid4()))
    cl.user_session.set("chat_history", [])


@cl.step(type="tool")
async def select_agent(query: str) -> str:
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    
    # Get the chat history from the user session or initialize it if it doesn't exist
    chat_history = cl.user_session.get("chat_history", [])
    
    # Format the chat history as expected by the classifier
    formatted_history = [
        ConversationMessage(
            role="user",
            content=[{"text": msg}]
        )
        for msg in chat_history
    ]
    
    # Add the current query to the formatted history
    formatted_history.append(
        ConversationMessage(
            role="user",
            content=[{"text": query}]
        )
    )
    
    # Perform classification
    classification = await orchestrator.classifier.classify(query, formatted_history)
    
    # Update the chat history with the new query
    chat_history.append(query)
    cl.user_session.set("chat_history", chat_history)
    
    # Prepare the output message
    output = "**Classifying Intent** \n"
    # output += "=======================\n"
    output += f"> Text: {query}\n"
    if classification.selected_agent:
            output += f"> Selected Agent: {classification.selected_agent.name}\n"
    else:
            output += "> Selected Agent: No agent found\n"
        
    output += f"> Confidence: {classification.confidence:.2f}\n"
        
    return output


@cl.on_message
async def main(message: cl.Message):
    user_id = cl.user_session.get("user_id")
    session_id = cl.user_session.get("session_id")
    
    msg = cl.Message(content="")
    
    agent_selection = await select_agent(message.content)
    await cl.Message(content=agent_selection).send()
    
    response = await orchestrator.route_request(message.content, user_id, session_id)
    
    # Prepare and send the initial metadata message
    metadata_message = f"\nMetadata:\n"
    metadata_message += f"Selected Agent: {response.metadata.agent_name}\n"
    await msg.stream_token(metadata_message)
    await msg.update()
    
    
    # Handle both regular and streaming responses
    if isinstance(response.output, ConversationMessage):
        # Handle regular response
        for chunk in response.output.content:
            await msg.stream_token(chunk['text'])
        await msg.update()
        
    else:
        # Handle streaming response
        async for chunk in response.output:
            if isinstance(chunk, str):
                await msg.stream_token(chunk)
            elif isinstance(chunk, dict) and 'text' in chunk:
                await msg.stream_token(chunk['text'])
            await msg.update()

if __name__ == "__main__":
    cl.run()