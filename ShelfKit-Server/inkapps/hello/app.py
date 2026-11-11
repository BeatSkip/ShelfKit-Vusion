"""hello - the smallest useful InkService: a counter you press from your phone.

The screen is layout.xml (InkLayout, see Documentation/InkLayout.md); this file only
says what data it shows and what the phone's buttons do.
"""

from shelfkit.inkservices import InkApp

app = InkApp("hello", title="Hello", description="A counter and a message, set from your phone",
             layout="layout.xml")
app.config_field("greeting", label="Greeting", default="Hello!")


@app.data
def data(tag):
    return {
        "greeting": tag.config.get("greeting", ""),
        "n": tag.data.get("n", 0),
        "message": tag.data.get("msg", ""),
    }


@app.button("Press me")
def press(tag):
    tag.data["n"] = tag.data.get("n", 0) + 1


@app.text_input("Message", placeholder="Leave a message on the tag")
def message(tag, text):
    tag.data["msg"] = text.strip()
    tag.log(f"message set ({len(tag.data['msg'])} chars)")
