from __future__ import annotations
import math, re

STYLES = {
    "cinematic": {"tone": "cinematic and evocative", "cta": "Stay with this story, and let it unfold."},
    "documentary": {"tone": "informative and measured", "cta": "Consider how this shapes the world around you."},
    "educational": {"tone": "clear and instructive", "cta": "Try applying this idea step by step today."},
    "explainer": {"tone": "simple and direct", "cta": "Now you have a clearer picture of how it works."},
    "news": {"tone": "factual and timely", "cta": "Keep following for more developments and updates."},
    "motivational": {"tone": "uplifting and energetic", "cta": "Take the first step now and keep moving forward."},
    "marketing": {"tone": "persuasive and engaging", "cta": "Discover more, get involved, and take action today."},
    "faceless": {"tone": "concise and engaging for social media", "cta": "Follow for more insights like this."},
}

WPM = 140  # planning rate; we intentionally over-generate slightly

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _expand_to_words(text: str, target_words: int, topic: str) -> str:
    """Expand text with meaningful, non-repetitive padding sentences until target reached."""
    fillers = [
        f"When we think about {topic}, it helps to slow down and notice the details that often go unseen.",
        f"Each part of {topic} connects to the next, creating a bigger picture that becomes clearer over time.",
        f"By paying attention to {topic}, we can understand not just what is happening, but why it matters.",
        f"There is real value in exploring {topic} from more than one angle, because perspective changes everything.",
        f"As this idea develops, {topic} continues to influence choices, habits, and outcomes in practical ways.",
        f"Taking a moment to reflect on {topic} can reveal opportunities that were easy to miss before.",
        f"The more we learn about {topic}, the easier it becomes to see its role in everyday life.",
        f"This is where {topic} becomes especially interesting, because small insights can lead to meaningful change.",
        f"Looking at {topic} carefully shows how progress is often built through steady, thoughtful steps.",
        f"In the end, {topic} reminds us that understanding grows when curiosity meets action.",
    ]
    words = text.split()
    i = 0
    while len(words) < target_words:
        words.extend(fillers[i % len(fillers)].split())
        i += 1
        if i > 200: break
    return " ".join(words)

def generate_script(topic: str, prompt: str, title: str, duration_min: int, style: str, language: str = "en") -> dict:
    topic = _clean(topic) or _clean(prompt) or "Your Topic"
    prompt = _clean(prompt)
    title = _clean(title) or topic[:80]
    duration_sec = max(60, min(300, int(duration_min) * 60))
    st = STYLES.get(style, STYLES["cinematic"])
    # More scenes for longer videos
    scene_count = max(4, min(20, round(duration_sec / 20)))
    target_words_total = max(120, round(duration_sec / 60 * WPM))

    starts_with_question = bool(re.match(
        r"(?i)^(how|what|why|when|where|who|which|can|could|do|does|did|is|are|was|were|should|will|would)\b", topic
    ))
    if starts_with_question:
        hooked = topic[:1].upper() + topic[1:]
        hook = f"{hooked}? That question sits at the center of a story most people never slow down to examine."
    else:
        hook = f"What if {topic} could change the way you see the world around you? " \
               f"Right now, there is more to this story than most people realize."
    intro = f"In this {st['tone']} video, we explore {topic}. " \
            f"{(prompt + ' ') if prompt else ''}Together, we will break it down step by step so it is easy to follow and remember."

    body_templates = [
        f"First, it is important to understand the foundation of {topic}. At a basic level, it begins with ideas and actions that shape what comes next. When you recognize these building blocks, the bigger picture starts to make sense.",
        f"Next, consider how {topic} shows up in real situations. It is not just an abstract concept; it influences decisions, behaviors, and results in ways we can observe every day. Seeing these connections makes the topic more practical and relevant.",
        f"There is also a deeper layer to {topic}. Beneath the surface, patterns begin to emerge. These patterns help explain why certain outcomes happen and how small changes can create a meaningful difference over time.",
        f"Another key point about {topic} is its impact. When people engage with it thoughtfully, they often discover new opportunities, clearer direction, and better ways to respond to challenges. That impact is what makes it worth exploring.",
        f"As we continue, it becomes clear that {topic} is always evolving. New perspectives, experiences, and insights keep adding to the story. Staying curious allows us to grow alongside it and adapt with confidence.",
        f"Finally, think about what {topic} means for the future. The choices made today can shape what happens tomorrow. By understanding it now, we put ourselves in a stronger position to move forward with purpose.",
        f"It also helps to connect {topic} to everyday goals. When ideas feel practical, they become easier to apply, and that is where real progress begins.",
        f"One more perspective on {topic} is the human side of the story. Behind every idea are people, experiences, and moments that give it meaning.",
    ]
    points = (body_templates * 4)[: max(2, scene_count - 2)]
    closing = f"So, as we reach the end, remember this: {topic} is more than a single idea — it is a journey of understanding, growth, and possibility. " \
              f"{st['cta']} Thank you for watching, and keep exploring what comes next."

    # target words per scene
    per_scene = max(30, round(target_words_total / scene_count))

    scenes = []
    remaining = duration_sec
    for i in range(scene_count):
        if i == 0:
            text = hook + " " + intro
            title_s = "Hook"
        elif i == scene_count - 1:
            text = closing
            title_s = "Closing"
        else:
            idx = i - 1
            text = points[idx] if idx < len(points) else f"Another important part of {topic} is how it continues to develop and influence the world around us. Paying attention to these changes helps us stay informed and prepared."
            title_s = ["Context", "Insight", "Deep Dive", "Impact", "Perspective", "Momentum", "Future", "Connection", "Meaning", "Takeaway", "Reflection", "Vision"][ (idx) % 12 ]

        # expand narration to meet per-scene target (drives TTS duration)
        text = _expand_to_words(text, per_scene, topic)

        # planned duration proportional, but actual render will follow audio
        slots_left = scene_count - i
        plan_dur = max(6, round(remaining / max(1, slots_left)))
        if i == scene_count - 1:
            plan_dur = max(6, remaining)
        plan_dur = min(plan_dur, remaining if i == scene_count - 1 else remaining - (scene_count - i - 1) * 5)
        plan_dur = max(5, plan_dur)
        remaining -= plan_dur

        scenes.append({
            "index": i,
            "title": title_s,
            "narration": text,
            "duration_sec": plan_dur,
            "visual_description": f"{st['tone'].capitalize()} visual representation of {topic}: {text[:140]}",
            "camera": ["slow_zoom_in", "slow_pan_right", "slow_zoom_out", "slow_pan_left"][i % 4],
            "transition": "fade" if i == 0 else ("fadeblack" if i == scene_count - 1 else "crossfade"),
            "sfx": "whoosh_soft" if i % 3 == 0 else "none",
            "text_overlay": (topic if i == 0 else (text.split('.')[0][:70] or topic)),
            "visual_kind": "animated_graphic",
        })
    total = sum(s["duration_sec"] for s in scenes)
    if total != duration_sec:
        scenes[-1]["duration_sec"] += (duration_sec - total)
        scenes[-1]["duration_sec"] = max(5, scenes[-1]["duration_sec"])

    full_text = "\n\n".join(s["narration"] for s in scenes)
    word_count = len(full_text.split())
    return {
        "title": title,
        "topic": topic,
        "prompt": prompt,
        "style": style,
        "language": language,
        "duration_sec": duration_sec,
        "scene_count": len(scenes),
        "word_count": word_count,
        "target_words": target_words_total,
        "hook": hook,
        "closing": closing,
        "full_text": full_text,
        "scenes": scenes,
        "generator": "deterministic-local-v2",
        "notes": "Locally generated editable script (no cloud LLM). Narration is expanded to target duration. Edit any scene before rendering.",
    }

def regenerate_scene(script: dict, scene_index: int) -> dict:
    topic = script.get("topic", "this topic")
    scenes = script.get("scenes", [])
    if scene_index < 0 or scene_index >= len(scenes):
        return script
    s = scenes[scene_index]
    variant = (s.get("variant", 0) + 1) % 4
    templates = [
        f"Let's revisit {topic} from a different perspective. When we take a closer look, new details come into focus and the meaning becomes richer. This view helps connect ideas in a way that feels practical and clear. By understanding these connections, we can appreciate how {topic} influences outcomes and opens the door to better decisions over time.",
        f"Another way to see {topic} is through its everyday impact. It shows up in small moments, steady habits, and important choices. Recognizing that influence makes the topic feel real and relevant. As we reflect on it, we can find opportunities to learn, improve, and move forward with greater confidence.",
        f"Looking deeper into {topic} reveals patterns that are easy to miss at first. These patterns explain how change happens and why certain steps matter more than others. With this understanding, the path ahead becomes easier to navigate. That clarity is what turns information into insight.",
        f"From a fresh angle, {topic} highlights both challenges and possibilities. Every challenge carries a lesson, and every possibility invites action. By staying curious and engaged, we can transform understanding into progress. That is how {topic} continues to matter in meaningful ways.",
    ]
    s["narration"] = _expand_to_words(templates[variant], max(40, len((s.get("narration") or "").split())), topic)
    s["visual_description"] = f"An alternative animated graphic visual for {topic}, scene {scene_index+1}."
    s["text_overlay"] = s["narration"].split('.')[0][:70]
    s["variant"] = variant
    scenes[scene_index] = s
    script["scenes"] = scenes
    script["full_text"] = "\n\n".join(x.get("narration","") for x in scenes)
    script["word_count"] = len(script["full_text"].split())
    return script
