# Product Vision

## Product

Telegram Health & Training Bot is a health and training assistant that helps an athlete decide what to do today, plan toward a running goal, and later collaborate with a real coach.

MVP is personal and single-user. The target product is a multi-user athlete/coach platform.

## Target Users

MVP:

- One athlete using Telegram.
- Connected devices: WHOOP and Garmin.

Future:

- Multiple athletes.
- Coaches who can view athlete data, review AI recommendations, edit plans, and discuss decisions with athletes.
- Additional connectors: Oura, Strava, and other health/training sources.

## Product Goals

The product should:

- Analyze accumulated device data up to the current day.
- Recommend what to do today.
- Propose a concrete workout when training is appropriate.
- Avoid unreasonable weekly load across running, cycling, swimming, strength, and walking.
- Support running-focused goals with strength training as support for running.
- Store enough raw data to re-analyze history later.
- Later support collaboration between athlete, AI, and human coach.

## MVP Priority

1. Daily assistant.
2. Goal planner.
3. AI chat with quick actions.

The first implementation should not start with a broad chat interface. It should first produce reliable daily recommendations.

## MVP Daily Recommendation

Daily recommendation format should be structured like:

```text
Статус дня: готовность 62/100

Главная рекомендация:
Легкая аэробная тренировка

Тренировка на сегодня:
Бег 35 минут:
- разминка 10 мин
- основной блок 20 мин Z2, пульс 130-145
- заминка 5 мин
- если пульс выше обычного, перейти на шаг

Почему:
HRV ниже среднего, сон 6ч 10м, вчера была высокая нагрузка, беговой объем недели уже 28 км

Чего избегать:
Интервалы, силовая до отказа

Контроль:
Если пульс выше обычного на 8-10 bpm, остановиться
```

If a workout has already been detected today, the assistant should account for it and may recommend recovery instead of additional load.

## MVP Activity Types

Support these normalized activity types:

- `run`
- `bike`
- `swim`
- `strength`
- `walk`
- `mobility`
- `recovery`
- `rest`
- `other`

Running is the primary sport. Strength supports running. Bike, swim, and walk count toward load and can be used as cross-training or recovery.

## MVP Goal Presets

Hard-code these presets initially:

- `run_10k_60` - 10 km in 60 minutes.
- `run_half_220` - half marathon in 2:20.
- `run_marathon_finish` - marathon without stopping.

Later, replace presets with configurable goals: distance, target time, target date, availability, constraints, and user level.

## Onboarding

On first `/start`, collect:

- Max heart rate.
- Active goal preset.
- Available training days.
- Maximum running days per week.
- Strength sessions per week.

Daily recommendation time is hard-coded for MVP:

```text
07:00 Europe/Belgrade
```

If max heart rate is later available from Garmin or WHOOP, the system may suggest updating the manually entered value. HR zones should be calculated from max HR in MVP and stored with the method used.

## Telegram MVP Menu

Main buttons:

- `Today` - today's recommendation and workout.
- `Goal` - choose or change goal preset.
- `Profile` - max HR, available days, running and strength limits.
- `Connect` - generate one-time web connect link.
- `History` - last 7 days.

Commands may mirror these actions:

- `/start`
- `/today`
- `/goal`
- `/profile`
- `/connect`
- `/history`

## History MVP

Show the last 7 days with:

- Date.
- Readiness/status.
- Recommendation.
- Planned workout.
- Actual volume for the day.
- Completion summary if available.

## Feedback

Do not show `Сделал` / `Не сделал` below every daily recommendation.

These actions apply to planned workouts after the workout has passed or when the bot asks about a specific planned workout:

- `Сделал`
- `Не сделал`
- Comment on how it went.

Feedback should attach to a planned workout, not to the general daily recommendation.

## Device Data

Use all device data that can be reasonably fetched from connected providers:

- Sleep.
- HRV.
- Resting heart rate.
- Recovery/readiness.
- Strain/load.
- Workouts.
- Intensity.
- Heart rate zones.
- Calories/activity.
- Steps.
- Body battery/stress if available.
- Respiratory rate, SpO2, skin temperature if available.
- Full raw payloads.

No manual daily check-in in MVP.

## Coach Platform Direction

Future coach functionality should be phased:

1. Coach sees athlete data and AI recommendations.
2. Coach comments on recommendations.
3. Coach creates or edits training plans.
4. Athlete and coach discuss plans.
5. Coach approves, rejects, or adjusts AI plans.

Model future records with source and status fields where relevant:

- `source`: `ai`, `coach`, `user`, `system`
- `status`: `draft`, `proposed`, `accepted`, `adjusted`, `completed`, `skipped`

