"""
Close all open documents in SolidWorks without saving.
Useful for cleaning up after test runs.
"""

import win32com.client
import pythoncom
import sys


def main():
    pythoncom.CoInitialize()

    try:
        sw = win32com.client.GetActiveObject("SldWorks.Application")
    except Exception:
        print("SolidWorks is not running.")
        return

    # Bounded loop: QuitDoc can decline to close a document (e.g. a modal
    # dialog is up), in which case ActiveDoc keeps returning the same doc.
    closed = 0
    last_title = None
    for _ in range(50):
        doc = sw.ActiveDoc
        if not doc:
            break
        title = doc.GetTitle
        if title == last_title:
            closed -= 1  # the previous QuitDoc didn't actually close it
            print(f"Could not close '{title}' (dialog open?); stopping.")
            break
        sw.QuitDoc(title)
        last_title = title
        closed += 1

    if closed:
        print(f"Closed {closed} document(s).")
    else:
        print("No documents were open.")


if __name__ == "__main__":
    main()
