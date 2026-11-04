import html
import re
from datetime import datetime, timezone


def clean(value):
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def matched_skills(job, profile):
    text = clean(" ".join([
        job.get("title", ""), job.get("description", ""),
        " ".join(job.get("tags", []) if isinstance(job.get("tags"), list) else [])
    ])).lower()
    return [skill for skill in profile.get("skills", []) if skill.lower() in text]


def generate_application(job, profile):
    """Create a truthful, editable application pack; never submits anything."""
    title = clean(job.get("title")) or "the position"
    company = clean(job.get("company")) or "the team"
    location = clean(job.get("location")) or "Remote"
    description = clean(job.get("description"))
    skills = matched_skills(job, profile)
    skills_text = ", ".join(skills[:4]) if skills else "visual design and creative work"
    name = profile.get("name") or "[YOUR NAME]"
    practice_years = profile.get("design_practice_years", "several")
    portfolio_url = (profile.get("portfolio_url") or "").strip()
    cv_url = (profile.get("cv_url") or "").strip()
    email = (profile.get("contact_email") or "").strip()
    salary = (job.get("salary") or "").strip()
    salary_expectation = (profile.get("salary_expectation") or "").strip()
    job_url = (job.get("url") or "").strip()

    cover_letter = (
        f"Hello {company} team,\n\n"
        f"I am applying for the {title} position. I am a designer based in Ukraine "
        f"with around {practice_years} years of design practice. "
        f"My creative work includes {skills_text}. I enjoy turning ideas into clear, "
        "thoughtful visuals and improving my work through feedback.\n\n"
        f"I would be glad to discuss how my skills could support {company}'s team. "
        "Thank you for considering my application.\n\n"
        f"Best regards,\n{name}"
    )
    if portfolio_url:
        cover_letter += f"\nPortfolio: {portfolio_url}"
    else:
        cover_letter += "\nPortfolio: [ADD YOUR PORTFOLIO LINK BEFORE SENDING]"

    email_subject = f"Application — {title}"
    email_body = (
        f"Hello {company} team,\n\n"
        f"I would like to apply for the {title} position. "
        "I have attached my application details and would be happy to discuss the role.\n\n"
        f"Best regards,\n{name}"
    )
    if portfolio_url:
        email_body += f"\nPortfolio: {portfolio_url}"
    else:
        email_body += "\nPortfolio: [ADD YOUR PORTFOLIO LINK]"
    if cv_url:
        email_body += f"\nCV: {cv_url}"

    intro = (
        f"My name is {name}. I am a designer from Ukraine with around "
        f"{practice_years} years of design practice. "
        f"My work includes {skills_text}. I am looking for a remote opportunity "
        "where I can contribute, learn and grow."
    )
    salary_answer = (
        f"My salary expectation is {salary_expectation}. I am open to discussing the final rate "
        "based on the responsibilities and workload."
        if salary_expectation else
        (
            f"The listing shows {salary}. I would be happy to discuss compensation "
            "based on the responsibilities and expected workload."
            if salary else
            "My salary expectation is open for discussion. Could you share the budgeted range "
            "for this role and the expected workload?"
        )
    )

    application_email = ""
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", description, re.I)
    if email_match:
        application_email = email_match.group(0)

    role_text = (title + " " + description).lower()
    portfolio_links = []
    portfolio_options = [
        ("3D / Blender", profile.get("portfolio_3d_url"), ["3d", "blender", "model", "character", "environment", "prop artist"]),
        ("Game Art", profile.get("portfolio_game_art_url"), ["game art", "game artist", "game asset", "unity", "unreal"]),
        ("Graphic / UI design", profile.get("portfolio_design_url"), ["graphic", "visual design", "ui/ux", "web design"]),
        ("Illustration", profile.get("portfolio_illustration_url"), ["illustration", "illustrator", "concept art", "book cover"])
    ]
    for label, url, keywords in portfolio_options:
        if url and any(word in role_text for word in keywords):
            portfolio_links.append({"label": label, "url": url})
    if portfolio_url and not any(item["url"] == portfolio_url for item in portfolio_links):
        portfolio_links.append({"label": "Main portfolio", "url": portfolio_url})
    portfolio_state = (
        "Selected: " + ", ".join(item["label"] for item in portfolio_links)
        if portfolio_links else
        "Missing: add a general or role-specific portfolio URL before sending."
    )
    if portfolio_links and not portfolio_url:
        selected_links_text = "\n".join(
            f"{item['label']}: {item['url']}" for item in portfolio_links
        )
        cover_letter = cover_letter.replace(
            "[ADD YOUR PORTFOLIO LINK BEFORE SENDING]", selected_links_text
        )
        email_body = email_body.replace("[ADD YOUR PORTFOLIO LINK]", selected_links_text)
    cv_state = f"Configured: {cv_url}" if cv_url else "No CV link configured."
    requirements = []
    for phrase in ["English", "portfolio", "resume", "CV", "Blender", "Figma",
                   "Photoshop", "Illustrator", "experience", "salary", "availability"]:
        if phrase.lower() in description.lower():
            requirements.append(phrase)

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revision": 1,
        "status": "awaiting_approval",
        "job": {
            "title": title, "company": company, "location": location,
            "url": job_url, "source": clean(job.get("source")),
            "salary": salary, "requirements_detected": requirements
        },
        "cover_letter": cover_letter,
        "email": {
            "to": application_email,
            "candidate_contact": email,
            "subject": email_subject,
            "body": email_body,
            "note": "Recipient is extracted only if an email address appears in the vacancy description."
        },
        "short_intro": intro,
        "answers": {
            "tell_us_about_yourself": intro,
            "why_this_role": (
                f"I am interested in this {title} opportunity because it matches my creative "
                f"interests and work with {skills_text}. I would like to contribute to the team "
                "and continue developing my skills."
            ),
            "salary_expectation": salary_answer,
            "english_level": f"My current English level is {profile.get('english_level', 'not specified')}.",
            "availability": "I can confirm my start date and weekly availability after reviewing the schedule."
        },
        "portfolio": {
            "url": portfolio_url,
            "links": portfolio_links,
            "status": portfolio_state,
            "approximate_items": profile.get("portfolio_items_approx"),
            "cv_url": cv_url,
            "cv_status": cv_state
        },
        "submission": {
            "destination_url": job_url,
            "destination_email": application_email,
            "instructions": [
                "Open the original vacancy page and verify that the role is still open.",
                "Check that the employer accepts applicants located in Ukraine.",
                "Use the application form or the verified email shown by the employer.",
                "Paste each prepared text into the matching field; attach the CV if requested.",
                "Add the real portfolio URL before sending."
            ],
            "requires_user_review": True,
            "will_submit_automatically": False
        },
        "checks": {
            "name_missing": not bool(profile.get("name")),
            "portfolio_url_missing": not bool(portfolio_links),
            "cv_url_missing": not bool(cv_url),
            "contact_email_missing": not bool(email),
            "salary_expectation_missing": not bool(profile.get("salary_expectation")),
            "country_eligibility_needs_verification": True,
            "claims_must_be_reviewed": True
        }
    }


def render_application_text(package):
    job = package["job"]
    email = package["email"]
    answers = package["answers"]
    portfolio = package["portfolio"]
    checks = package.get("checks", {})
    profile_gaps = []
    if checks.get("name_missing"):
        profile_gaps.append("Не вказано повне ім'я кандидата.")
    if checks.get("cv_url_missing"):
        profile_gaps.append("Не налаштовано посилання на CV.")
    if checks.get("contact_email_missing"):
        profile_gaps.append("Не вказано контактну пошту.")
    if checks.get("salary_expectation_missing"):
        profile_gaps.append("Не задано бажану оплату.")
    if checks.get("country_eligibility_needs_verification"):
        profile_gaps.append("Потрібно перевірити, чи наймають кандидатів з України.")
    if checks.get("claims_must_be_reviewed"):
        profile_gaps.append("Перевір твердження про досвід та навички.")

    lines = [
        "🧾 <b>ПАКЕТ ЗАЯВКИ · MYSHKA</b>",
        f"<b>{job['title']}</b> · {job['company']}",
        f"📍 {job['location']}",
        "",
        "<b>1. COVER LETTER</b>",
        package["cover_letter"],
        "",
        "<b>2. EMAIL</b>",
        f"To: {email['to'] or 'Не знайдено в описі вакансії'}",
        f"Your contact: {email.get('candidate_contact') or 'Додай свою контактну пошту, якщо роботодавець просить'}",
        f"Subject: {email['subject']}",
        email["body"],
        "",
        "<b>3. КОРОТКЕ ПРЕДСТАВЛЕННЯ</b>",
        package["short_intro"],
        "",
        "<b>4. ВІДПОВІДІ ДЛЯ АНКЕТИ</b>",
        f"About yourself: {answers['tell_us_about_yourself']}",
        f"Why this role: {answers['why_this_role']}",
        f"Salary: {answers['salary_expectation']}",
        f"English: {answers['english_level']}",
        f"Availability: {answers['availability']}",
        "",
        "<b>5. ПОРТФОЛІО / CV</b>",
        portfolio["status"],
        *[f"{item['label']}: {item['url']}" for item in portfolio.get("links", [])],
        f"Approximate portfolio items: {portfolio.get('approximate_items') or 'not specified'}",
        portfolio["cv_status"],
        "",
        "<b>6. ПЕРЕВІРКА ПРОФІЛЮ</b>",
        *([f"⚠️ {item}" for item in profile_gaps] or ["✅ Базові дані профілю налаштовані."]),
        "",
        "<b>7. КУДИ ПОДАВАТИ</b>",
        job["url"] or "Посилання відсутнє — потрібна ручна перевірка.",
        *[f"• {step}" for step in package["submission"]["instructions"]],
        "",
        "⚠️ Перевір усі тексти. Це чернетки, не відправлена заявка."
    ]
    return "\n".join(lines)
