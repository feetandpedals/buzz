"""One-time page: save the AI key into Windows Credential Manager (never to a file)."""
import keyring
import streamlit as st

SERVICE = "ai-reel-studio"
st.set_page_config(page_title="Buzz setup")
st.title("Buzz: one-time setup")
have = keyring.get_password(SERVICE, "anthropic") is not None
st.write("Key status: **saved**" if have else "Key status: **not saved yet**")
key = st.text_input("Paste your Claude API key here", type="password")
if st.button("Save key securely") and key.strip():
    keyring.set_password(SERVICE, "anthropic", key.strip())
    st.success("Saved in Windows Credential Manager. You can close this page.")
st.caption("The key is stored by Windows, not in any project file.")
