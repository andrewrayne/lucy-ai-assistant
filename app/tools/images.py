"""Create images with Gemini and send them to the owner in Telegram."""

from google.genai import types

from app import costs
from app.bot import outbox
from app.config import get_settings
from app.gemini import client
from app.tools.registry import registry


@registry.register(
    "generate_image",
    "Create an image from a description and send it to the owner in Telegram "
    "(illustrations, thumbnails ideas, mockups, diagrams, photos of things that don't exist).",
    {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Detailed description: subject, style, composition, mood."},
            "caption": {"type": "string", "description": "Short caption under the image (optional)."},
        },
        "required": ["prompt"],
    },
)
async def generate_image(prompt: str, caption: str = "") -> dict:
    response = await client().aio.models.generate_content(
        model=get_settings().gemini_image_model,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )
    parts = response.candidates[0].content.parts if response.candidates else []
    images = [p.inline_data for p in parts if p.inline_data and p.inline_data.mime_type.startswith("image/")]
    costs.record("gemini-image", get_settings().gemini_image_model, costs.IMAGE_PRICE * max(len(images), 1))
    if not images:
        return {"error": "The image model returned no image. Try rephrasing the description."}
    ext = images[0].mime_type.split("/")[-1].replace("jpeg", "jpg")
    await outbox.send_photo(images[0].data, caption, filename=f"image.{ext}")
    return {"status": "image sent to the owner in Telegram (don't describe it at length)"}
