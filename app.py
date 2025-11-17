from flask import Flask, render_template, request, redirect, url_for
import PyPDF2
import cohere
import re
from markupsafe import Markup

app = Flask(__name__)

COHERE_API_KEY = "bJRWUdCALOOsa9ggDr6f3TI9k006FmPhxCMoI2vZ"
co = cohere.Client(COHERE_API_KEY)

def format_text(text):
    """Convert markdown-style formatting to HTML"""
    if not text:
        return ""
    
    # First, escape any HTML characters except what we'll generate
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = text.replace('&amp;amp;', '&amp;').replace('&lt;br&gt;', '<br>')
    
    # Convert **bold** to <strong>bold</strong> (greedy to handle multiple asterisks)
    text = re.sub(r'\*{2,}([^\*]+?)\*{2,}', r'<strong>\1</strong>', text)
    
    # Convert *italic* to <em>italic</em> (single asterisks, but not already converted)
    text = re.sub(r'(?<!\*)\*(?!\*)([^\*]+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
    
    # Remove any remaining stray asterisks
    text = re.sub(r'\*+', '', text)
    
    # Convert - bullet points to HTML list items
    text = re.sub(r'^- (.+)$', r'<li>\1</li>', text, flags=re.MULTILINE)
    # Wrap consecutive <li> in <ul>
    text = re.sub(r'(<li>.+?</li>)', r'<ul>\1</ul>', text, flags=re.DOTALL)
    # Clean up multiple <ul> wraps
    text = re.sub(r'</ul>\s*<ul>', '', text)
    
    # Convert line breaks to <br>
    text = text.replace('\n', '<br>')
    
    return Markup(text)

def parse_feedback(feedback_text):
    """Parse AI feedback into structured sections and overall grade"""
    sections = re.split(r'---+', feedback_text)
    parsed = []
    overall = ""
    
    # First, try to extract overall grade from the entire feedback text
    # Look for patterns like "Overall Grade: 85" or "Overall Grade: 85/100" or just "85"
    overall_match = re.search(r'Overall\s+Grade:\s*(\d+)', feedback_text, re.IGNORECASE)
    if overall_match:
        overall = overall_match.group(1)
    
    for sec in sections:
        lines = [line.strip() for line in sec.strip().splitlines() if line.strip()]
        if not lines:
            continue
        
        # Skip the section if it only contains overall grade info
        if len(lines) == 1 and "Overall Grade" in lines[0]:
            if not overall:  # Only update if we haven't found it yet
                overall_text = lines[0].replace("Overall Grade:", "").strip()
                grade_match = re.search(r'(\d+)', overall_text)
                overall = grade_match.group(1) if grade_match else overall_text
            continue
        
        # Process regular feedback sections
        if lines:
            # Clean up title - remove "Section Title:" prefix and special characters
            title = lines[0]
            title = re.sub(r'^Section\s+Title:\s*', '', title, flags=re.IGNORECASE)
            title = re.sub(r'^\*+', '', title)  # Remove leading asterisks
            title = re.sub(r'\*+$', '', title)  # Remove trailing asterisks
            title = title.strip()
            
            # Skip if this is just the overall grade line
            if "Overall Grade" in title or not title:
                continue
            
            score_match = re.search(r'Score:\s*(\d+)/(\d+)', sec)
            score = score_match.group(1) if score_match else "-"
            comments = ""
            suggestions = ""
            comment_start = sec.find("Comments:") + len("Comments:")
            suggest_start = sec.find("Suggestions:")
            if comment_start >= 0 and suggest_start > 0:
                comments = format_text(sec[comment_start:suggest_start].strip())
                suggestions = format_text(sec[suggest_start + len("Suggestions:"):].strip())
            
            parsed.append({
                "title": title,
                "score": score,
                "comments": comments,
                "suggestions": suggestions
            })
    
    # If still no overall grade found, default to 0
    if not overall:
        overall = "0"
    
    return parsed, overall

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        essay_text = ""
        rubric = request.form.get("rubric", "")
        pdf_file = request.files.get("pdf_file")
        if pdf_file:
            reader = PyPDF2.PdfReader(pdf_file)
            essay_text = "\n".join([page.extract_text() for page in reader.pages])
        paste_text = request.form.get("essay_text", "")
        if paste_text:
            essay_text = paste_text
        if not essay_text:
            return render_template("upload.html", error="Upload PDF or paste your essay!")
        
        prompt = f"""
        Grade the following essay with structured rubric feedback:
        {rubric if rubric else 'Default rubric: Thesis, Evidence, Organization, Grammar, Style'}

        Essay:
        {essay_text}

        Format output clearly with:
        Section Title
        Score X/Y
        Comments
        Suggestions
        Overall Grade XX/100
        Separate sections with ---
        """
        try:
            response = co.chat(
                model='command-xlarge-nightly',
                message=prompt,
                max_tokens=800,
                temperature=0.3
            )
            feedback_text = response.text
            sections, overall_grade = parse_feedback(feedback_text)
            return render_template("result.html", sections=sections, overall_grade=overall_grade, essay=essay_text)
        except Exception as e:
            return render_template("upload.html", error=f"Error generating AI feedback: {e}")
    return render_template("upload.html")

if __name__ == "__main__":
    app.run(debug=True)
