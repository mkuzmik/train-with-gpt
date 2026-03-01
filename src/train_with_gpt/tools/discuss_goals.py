"""Discuss goals tool."""

from mcp.types import Tool, TextContent


def discuss_goals_tool() -> Tool:
    """Return the discuss_goals tool definition."""
    return Tool(
        name="discuss_goals",
        description="Get guidance on how to have a structured goal-setting conversation with the user. Returns a framework for discussing training goals.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


async def discuss_goals_handler(arguments: dict) -> list[TextContent]:
    """Handle discuss_goals tool calls."""
    guidance = """# Training Goal Setting Framework

**IMPORTANT: Before discussing goals, use `get_last_week_activities` to see the user's recent training data. This provides context about their current fitness level and training patterns.**

## Conversation Style:

**ASK ONE QUESTION AT A TIME.** This is a conversation, not an interview. 
- Wait for the user's answer before asking the next question
- Build on their responses naturally
- Don't overwhelm with multiple questions at once

## Key Topics to Cover:

### 1. Primary Goal
- What are they training for? (event, race, personal milestone)
- Specific target (time, distance, placement)
- Target date
- Why this goal matters to them

### 2. Current Fitness
- Recent performance benchmarks (check last week's activities first!)
- Current training volume
- Training background and experience

### 3. Constraints & Context
- Available time per week
- Injury history or limitations
- Life commitments
- Training environment/equipment

### 4. Secondary Priorities
- Stay healthy/injury-free
- Enjoy the process
- Balance with life
- Other fitness goals

## Workflow:

1. **First**: Call `get_last_week_activities` to see their recent training
2. **Then**: Start the conversation with ONE question about their primary goal
3. **Continue**: Ask follow-up questions one at a time based on their answers
4. **Finally**: Write a comprehensive summary and use `save_goals`

## Conversation Example:

❌ BAD (multiple questions):
"What race are you training for? What's your target time? When is the race? Do you have any injuries? How many days can you train?"

✅ GOOD (one at a time):
User: "I want to set some training goals"
You: "I can see from your recent activities that you're running consistently. What are you training for?"

User: "A 5k race in March"
You: "Great! Do you have a specific time goal in mind?"

User: "I want to break 17 minutes"
You: "That's an ambitious goal. What's your current 5k best?"

## After the Conversation:

Write a clear, natural language summary covering:
- The primary goal with specifics
- Current state and starting point (reference recent activities you observed)
- Key constraints or considerations
- Timeline and milestones
- What success looks like

Then use **save_goals** to persist this summary.

## Example Summary:

"The athlete is training for a 5km race on March 15th, 2026, with a goal of breaking 17 minutes. 
Their current 5km best is 18:30 from a recent parkrun. 

Looking at last week's training: they're running consistently with several quality sessions including 
a 13km run at 4:16/km pace and regular recovery runs around 5:15/km. Weekly volume appears to be 
around 40-50km. The data shows good pacing control and consistent heart rate management.

Key constraints: History of shin splints, so need to be careful with intensity progression. Can train 
5-6 days per week, with Wednesdays reserved for cross-training or rest due to work schedule.

The training plan should prioritize staying injury-free while building speed through interval work and 
tempo runs. Success means both achieving the time goal AND arriving at race day healthy and confident."

This natural format captures nuance and context better than rigid structure."""

    return [TextContent(type="text", text=guidance)]
