from pydantic import BaseModel


class ChatMessageSchema(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessageSchema]
    stream: bool = False


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessageSchema
    finish_reason: str = "stop"


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    model: str
    choices: list[ChatCompletionChoice]
    usage: dict


class ChatCompletionChunkDelta(BaseModel):
    role: str | None = None
    content: str | None = None


class ChatCompletionChunkChoice(BaseModel):
    index: int = 0
    delta: ChatCompletionChunkDelta
    finish_reason: str | None = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    model: str
    choices: list[ChatCompletionChunkChoice]


class ErrorDetail(BaseModel):
    message: str
    type: str
    code: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
