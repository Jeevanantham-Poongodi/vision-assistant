# Member 5 — Your Plan: Testing, Demo & Presentation

**Who this is for:** Member 5, the team's **Test Lead and Presenter**.
**You do not need to write code.** Everything in this guide is clicking, checking, measuring, filming, writing and presenting. When a step uses a technical word, it is explained the first time, and there is a word list in section 3.

**How to read this guide**
1. Read sections 1–5 once, today, before the hackathon.
2. During the hackathon, follow section 5 (your timeline) and open the task it points to.
3. Every 4 hours, follow section 7 (your checkpoint job). This is your most important job.

---

## Contents

1. Your role in one minute
2. What we are building, in plain words
3. Words you will hear (and what they mean)
4. What to prepare before the hackathon
5. Your timeline, hour by hour
6. Your tasks, step by step (QA-01 to QA-08)
7. Your checkpoint job: running the tests every 4 hours
8. How to report a problem
9. Your tracker spreadsheet
10. The pitch deck, slide by slide
11. The live demo run sheet
12. Demo-day checklist
13. Who to ask for what
14. Your golden rules

---

## 1. Your role in one minute

You are the team's **quality checker** and **storyteller**.

- **Before the coders need them**, you prepare test material: sample data, photos, video clips and a set of ready-made test requests.
- **Every 4 hours**, the team joins everyone's work together. You run the checks and decide **pass or fail**. Nothing reaches the final version of the project without your OK.
- **Throughout**, you measure how well the product works (how accurate the distances are, how fast warnings arrive). Those numbers go into the presentation.
- **At the end**, you own the pitch deck, the live demo script and a backup demo video.

You are the only person on the team who sees the whole product the way the judges will see it. That is why your "this doesn't work" or "this is confusing" matters as much as any line of code.

---

## 2. What we are building, in plain words

A phone app that acts as **"eyes" for a visually impaired person**.

1. The person wears a phone on their chest with the camera facing forward.
2. The phone sends what the camera sees to our computer (the "server") several times per second.
3. The server's AI recognises things like people, cars, chairs and dogs, works out **which side** they are on (left, ahead, right) and **roughly how far** away they are.
4. If something is dangerous or close, the phone **speaks a warning**, for example:
   > *"Warning. Car approaching from your right, approximately 4 meters away. Please move slightly to your left."*
5. A **guardian** (family member or helper) can watch from a laptop: they see what the camera sees, get alerts, and can send spoken instructions to the person.
6. The person can also **ask questions** ("What is in front of me?") and ask the phone to **read signs** aloud.

**The five things that must work (the "MVP", minimum version we must show):**
camera feed · object recognition · approximate distance · direction · spoken warning.

Everything else (guardian dashboard, questions, sign reading, map) is a bonus on top.

---

## 3. Words you will hear (and what they mean)

| Word | What it means for you |
|---|---|
| **Frontend** | The screens people see: the user's phone page and the guardian's dashboard. Built by Coder 1 |
| **Backend / server** | The program running on the laptop that receives camera images and runs the AI. Built by Coder 3 |
| **AI vision / YOLO** | The part that recognises objects in a picture. Built by Coder 2 |
| **Gemini** | Google's AI that answers spoken questions. Used by Coder 4 |
| **OCR** | "Optical character recognition": reading text from a photo, such as a sign |
| **API** | The set of "doors" through which the screens talk to the server. Each door has an address |
| **Endpoint** | One of those doors, e.g. `/health` ("are you alive?") or `/emergency` ("send an emergency") |
| **Request / response** | You send a request to an endpoint; the server sends back a response. Like sending a letter and getting a reply |
| **Status code** | A number on every response. **200/201/202 = OK.** **400/404/409/422 = you sent something wrong (expected in error tests).** **500/503 = the server broke (always a bug)** |
| **JSON** | The text format used for messages: curly brackets `{ }`, names in quotes, values after colons. You copy and paste it; you do not need to write it from scratch |
| **Mock data** | Fake but realistic sample messages, so coders can build screens before the real thing works |
| **Postman** | A free app for sending requests to the server and checking the replies, without needing the phone app |
| **WebSocket** | A live, always-open connection (like a phone call instead of letters). Used for the camera stream and live alerts |
| **Session** | One "run" of the assistant, from pressing Start to pressing Stop |
| **Tunnel / HTTPS address** | A secure web address that lets the phone reach the laptop over the internet. Phones only allow the camera on secure (`https://`) addresses |
| **Latency** | Delay: how long from the camera seeing something to the warning appearing. Lower is better |
| **fps** | "Frames per second": how many camera pictures per second the server handles. We need at least **4** |
| **GitHub / repository (repo)** | The online folder where all the team's files live, with full history |
| **Branch** | Each person's own copy of the project. Yours is called **`qa-docs`**. Nobody works directly on `main`, the final version |
| **Commit** | Saving a change into the repo, with a short note saying what you changed |
| **Merge** | Combining branches. At each checkpoint, everyone's branches are merged into a test branch called `integration` |
| **PR (pull request)** | A request to move the tested work into `main`. **You approve it** when your tests pass |
| **Checkpoint (CP0–CP5)** | The every-4-hours moment when everything is joined and tested. You run the tests |
| **Feature flag** | An on/off switch for an unfinished feature, so it can be hidden without deleting it |
| **Bug severity S1 / S2 / S3** | How bad a problem is. Explained in section 8 |

---

## 4. What to prepare before the hackathon

### 4.1 Accounts and apps (on your laptop)
- [ ] **GitHub account**, and ask Coder 3 to add you to the team repository.
- [ ] **Postman** desktop app (free) installed and signed in. Desktop app, not the website: the website cannot reach a server running on a laptop.
- [ ] **Google Sheets** (or Excel) for the tracker (section 9).
- [ ] The team's presentation tool (Google Slides, PowerPoint or Canva). Agree with the team which one.
- [ ] Google Chrome browser, up to date.

### 4.2 Physical kit (bring in one bag)

| Item | Why |
|---|---|
| Measuring tape, 5 m or longer | Distance accuracy tests |
| Masking tape (coloured if possible) | Marking 1 m, 2 m, 3 m, 4 m, 5 m on the floor |
| Marker pen | Writing the numbers on the tape |
| A second phone (yours) | Filming tests, stopwatch, backup recording |
| Printed signs, A4, large letters: "ROOM 204", "LIBRARY ←", "COMPUTER SCIENCE DEPARTMENT", "EXIT →", a short notice paragraph | Sign-reading (OCR) tests and the live demo |
| A product with a clear label (water bottle, biscuit packet) | "What is this?" and label-reading tests |
| A chest strap, lanyard phone holder or a cloth bag with a hole for the camera | So the demo user can wear the phone facing forward |
| A sleep mask or blindfold | For the demo user (shows the judges the user cannot see) |
| Power bank + charging cables + an extension cord | Phones die during long tests |
| A folding chair (or borrow one at the venue) | Obstacle tests |

### 4.3 Read these files once
- `00_TEAM_PLAN.md`: the overview (5 minutes).
- `API_CONTRACTS.md` **section 13** only: the sample messages (you will upload these).
- This guide.

---

## 5. Your timeline, hour by hour

"H+4" means **4 hours after the hackathon starts**. If your hackathon is longer than 24 hours, keep the order and stretch the times.

| When | What you do | Task |
|---|---|---|
| **H+0 → H+1** | Upload the sample data files. Set up Postman. Create the tracker spreadsheet | QA-01, start QA-02, section 9 |
| **H+1** | **Checkpoint 0**: quick test (15 minutes) | Section 7 |
| **H+1 → H+4** | Take the 20 test photos. Finish Postman setup. Prepare the checklists | QA-02, QA-03, QA-04 |
| **H+4** | **Checkpoint 1**: first time the phone talks | Section 7 |
| **H+4 → H+8** | Film the 4 test clips with Coder 2. Measure distance accuracy with the tape. Measure speed | QA-05 |
| **H+8** ★ | **Checkpoint 2**: the most important test of the event | Section 7 |
| **H+8 → H+12** | Add guardian tests in Postman. Draft the pitch deck outline | QA-06 |
| **H+12** | **Checkpoint 3**: guardian dashboard | Section 7 |
| **H+12 → H+16** | Write the demo run sheet. Full re-test of everything so far | QA-07 |
| **H+16** | **Checkpoint 4**: all features | Section 7 |
| **H+16 → H+20** | Network-failure drill. Record the backup demo video. Finish the deck | QA-08 |
| **H+20** | **Checkpoint 5**: final version | Section 7 |
| **H+20 → end** | 3 full rehearsals with timing. Final deck. Rest before presenting | Sections 11, 12 |

> **Take your breaks between checkpoints, never during one.** The team cannot finish a checkpoint without you.

---

## 6. Your tasks, step by step

Each task has: **why it matters**, **what you need**, **steps**, and **done when**.

### QA-01 · Upload the sample data (first hour, urgent)

**Why it matters:** Coder 1 cannot build the phone screens until these sample messages exist. You are unblocking them.

**What you need:** the folder `member5-starter-kit/` (already prepared for you), access to the GitHub repo.

**Steps**
1. Open the team repository on github.com in Chrome.
2. Top left, click the **branch dropdown** (it usually says `main`). Choose **`qa-docs`**. Check it now says `qa-docs`. *(Always check this before uploading anything.)*
3. Click into the folder `frontend`, then `src`.
4. Click **Add file → Upload files**.
5. From `member5-starter-kit/frontend/src/`, **drag the whole `mocks` folder** into the browser window. (Dragging the folder keeps its name.)
6. At the bottom, in the message box, type: `[QA-01] add mock data for frontend`.
7. Make sure **"Commit directly to the `qa-docs` branch"** is selected. Click **Commit changes**.
8. Go back to the repository's main page (still on `qa-docs`). Open `backend`, then `tests`. Upload the `fixtures` folder from `member5-starter-kit/backend/tests/` the same way, message `[QA-01] add test fixtures`.
9. Go back to the main page again and upload the whole `postman` folder at the top level, message `[QA-02] add Postman collection`.
10. Tell the team in chat: *"QA-01 done: mocks are on qa-docs in frontend/src/mocks and backend/tests/fixtures."*

**Done when:** the files are visible on GitHub in the `qa-docs` branch, in the right folders.

> If GitHub says you cannot commit, you may be on `main` (which is locked). Switch to `qa-docs` and try again.

### QA-02 · Postman: your remote control for the server

**Why it matters:** Postman lets you test the server directly, without the phone app. When something breaks, it tells the team whether the problem is in the server or in the screens.

**What you need:** Postman desktop, the `postman/` folder from the starter kit, the server address from Coder 3.

**Part A: set up (do once)**
1. Open Postman. Click **Import** (top left). Drag in these three files from `postman/`:
   - `VisionAssistant.postman_collection.json` (all the test requests)
   - `Local.postman_environment.json` (settings for when the server runs on the same laptop)
   - `Tunnel.postman_environment.json` (settings for the secure web address used by the phone)
2. Top right, there is an **environment dropdown** (it says "No environment"). Choose **"Vision – Local laptop"** if Postman is on the laptop running the server. Otherwise choose **"Vision – Tunnel (phone demo)"**.
3. If you use the Tunnel environment: click **Environments** (left sidebar) → "Vision – Tunnel" → in `base_url`, replace `PASTE-TUNNEL-ADDRESS-HERE` with the address Coder 3 gives you (keep `https://` at the start and `/api/v1` at the end) → **Save**. The address changes each time the tunnel restarts, so update it when Coder 3 posts a new one.

**Part B: how the collection is organised**
The collection has numbered folders. Each one becomes useful from a certain checkpoint:

| Folder | Works from | What it tests |
|---|---|---|
| 1. Basics | CP0 | Is the server alive? Does it return its settings? |
| 2. Sessions | CP1 | Starting and finding a session, plus 3 deliberate mistakes |
| 3. Detection | CP2 | Send a photo, get back recognised objects |
| 4. Guardian & alerts | CP3 | Emergency, alerts, acknowledging |
| 5. Voice features | CP4 | Guardian messages, Ask AI, reading text |
| 9. Clean up | Any time | Ends the test session |

Requests whose names start with **"ERROR:"** are deliberate mistakes. They **should** return an error number (400, 404, 409 or 422). If they return 200, that is a bug: the server accepted something wrong.

**Part C: running the tests**
1. Right-click a folder → **Run folder**. In the runner window, click **Run**. Postman sends each request in order and shows green (pass) or red (fail) for every check.
2. Requests with a photo ("Detect objects", "Read text", and the "ERROR: non-image" one): open the request → **Body** tab → next to `image`, click **Select Files** → choose a photo from your photo pack (for the ERROR one, any `.txt` file) → press **Ctrl+S** to save. Do this once; Postman remembers it for later runs.
3. **Always run folder 2 before folders 3–5**: "Start session" saves the session number automatically for the later requests.
4. To see what the AI found, open **Console** (bottom left in Postman). The detection test prints lines like `car right 4.2m high`.

**Part D: the live connection test (WebSocket)**
The camera stream uses a live connection, which needs a slightly different kind of request.
1. In Postman: **New → WebSocket**.
2. Address: the tunnel address but starting with `wss://` instead of `https://`, ending with `/ws/user/` and the session number. For example:
   `wss://abc-def.trycloudflare.com/ws/user/5d0e2b7c-8f6a-4f1e-9a43-0c6f6d1b2a10`
   (copy the session number from the environment's `session_id` after running "Start session").
3. **Before connecting**, open `postman/websocket-messages/user_hello.json` in a text editor, copy everything, and paste it into Postman's message box. (The server closes the connection if it gets no hello within 5 seconds, so it must be ready.)
4. Click **Connect**, then immediately click **Send**. Expected reply: a message containing `"type": "welcome"`. If you see "Disconnected" with code 4003, you were too slow; connect and send again.
5. Then send these, one at a time, and check the reply:

| File to paste | Expected reply contains |
|---|---|
| `ping.json` | `"type": "pong"` |
| `user_frame_small.json` | `"type": "frame_result"` (from CP1 on) |
| `user_frame_broken.json` | `"type": "error"` and `INVALID_FRAME`, and the connection **stays open** |
| `user_unknown_type.json` | `"type": "error"` and `UNSUPPORTED_MESSAGE`, connection stays open |
| `user_emergency.json` (CP3+) | `"type": "emergency_ack"` |

6. Save this WebSocket request in Postman (Ctrl+S) as "User live connection" so you can reuse it.

**Done when:** folders 1 and 2 run green against the real server at CP1, and the WebSocket hello/ping work.

### QA-03 · The test photo pack and the "golden sentences"

**Why it matters:** the same photos are used at every checkpoint, so we can tell if the AI got better or worse. The golden sentences are the exact words the phone should say. You will listen and compare.

**What you need:** the **demo phone** (the actual phone used on stage), the printed signs, a helper.

**Steps: photos**
1. Set the demo phone camera to a **medium** photo size (Settings in the camera app). Photos must be under 5 MB. If they are bigger, send them to yourself on WhatsApp or Telegram as a photo (this shrinks them) and save from there.
2. Hold the phone at **chest height**, landscape (sideways), and take these 20 photos:

| # | File name | What to photograph |
|---|---|---|
| 1 | `01_person_1m_center.jpg` | A person standing 1 m in front, centred |
| 2 | `02_person_2m_center.jpg` | Same person at 2 m |
| 3 | `03_person_3m_center.jpg` | At 3 m |
| 4 | `04_person_5m_center.jpg` | At 5 m |
| 5 | `05_person_2m_left.jpg` | Person at 2 m on the far left of the picture |
| 6 | `06_person_2m_right.jpg` | Person at 2 m on the far right |
| 7 | `07_chair_70cm.jpg` | A chair 70 cm ahead, centred |
| 8 | `08_chair_2m_left.jpg` | Chair 2 m away, left side |
| 9 | `09_two_people.jpg` | Two people at different distances |
| 10 | `10_car_parked.jpg` | A parked car, about 4 m away, on the right |
| 11 | `11_motorbike.jpg` | A two-wheeler, about 3 m away |
| 12 | `12_street_busy.jpg` | A busy street or corridor with several people |
| 13 | `13_empty_corridor.jpg` | An empty corridor or path, nothing in it |
| 14 | `14_dark_room.jpg` | A dim room with a person in it |
| 15 | `15_sign_room204.jpg` | The printed "ROOM 204" sign, filling half the picture |
| 16 | `16_sign_library_arrow.jpg` | The "LIBRARY ←" sign |
| 17 | `17_sign_department.jpg` | "COMPUTER SCIENCE DEPARTMENT" |
| 18 | `18_notice_paragraph.jpg` | The printed notice paragraph |
| 19 | `19_product_label.jpg` | The bottle or packet, label facing the camera |
| 20 | `20_dog_or_animal.jpg` | A dog, cow or other animal if you find one safely (otherwise a bench or plant pot) |

3. Upload them to GitHub on `qa-docs`, in `backend/tests/fixtures/photos/` (same upload steps as QA-01), message `[QA-03] add test photo pack`.

**Steps: golden sentences sheet**
1. In your tracker (section 9), open the tab **"Golden sentences"**.
2. Copy the table from `API_CONTRACTS.md` section 13.7: situation in one column, the exact expected sentence in the next.
3. Add three empty columns: **"What the phone actually said"**, **"Match? (Yes/No)"**, **"Checkpoint"**.
4. Whenever you hear the phone say something wrong or awkward, add a new row and tell Coder 4.

**Done when:** 20 photos are on GitHub and the golden sheet exists.

### QA-04 · Prepare the checkpoint checklists

**Why it matters:** at each checkpoint, everyone is tired and in a hurry. A written checklist means nothing gets skipped.

**Steps**
1. In your tracker, create one tab per checkpoint: **CP0, CP1, CP2, CP3, CP4, CP5**.
2. Copy the checks for each checkpoint from section 7 of this guide into its tab, one check per row.
3. Columns: **#**, **Check**, **Expected result**, **Pass / Fail**, **Notes**, **Bug link**.
4. Each time a checkpoint passes, its checks are **added to the next one too** ("regression": making sure old things still work). You do not need to copy them; just re-run the earlier tabs.

**Done when:** all six tabs exist with their checks.

### QA-05 · Measure accuracy and speed (with Coder 2)

**Why it matters:** judges ask "how accurate is it?" A real table of measured numbers is far more convincing than "it's pretty accurate".

**Part A: test clips (with Coder 2)**
Film 4 short videos on the **demo phone**, held at chest height, landscape, 10–20 seconds each:
1. A person walking slowly towards the camera from about 6 m to 1 m.
2. A chair placed 70 cm in front of the camera.
3. A vehicle passing on the right (a parking area is fine; **stay safely off the road**).
4. An empty corridor, slowly walking forward.

Give the files to Coder 2. They use them to replay tests without walking into traffic.

**Part B: distance accuracy**
1. On a flat floor, put masking tape at **1 m, 2 m, 3 m, 4 m and 5 m** from a starting line. Write the number on each piece.
2. Put the demo phone on a chair or hold it at chest height on the starting line, pointing along the tape.
3. Open the app on the phone with the **detection overlay switched on** (Coder 1 shows you the switch). Each recognised object has a label like `person · ahead · 2.1 m`.
4. A person stands on each mark. For each mark, write down the distance shown, **3 times**, a few seconds apart.
5. Repeat with the chair.
6. Fill the **"Distance accuracy"** tab in your tracker (section 9). The sheet calculates the average and the error % for you.
7. Send the table to Coder 2. If the error is above 25%, they will re-calibrate.

**Part C: speed**
1. **Pictures per second and delay:** the phone app shows a small debug strip with `fps` and `latency` (in milliseconds, ms; 1000 ms = 1 second). Every 30 seconds for 5 minutes, write both numbers in the **"Speed"** tab.
   - Target: fps **4 or more**, latency **under 400 ms**.
2. **"Seen to spoken" time:** film with your own phone, standing behind the demo user so both the demo phone's view and its sound are recorded. Push the chair into the camera's view. Later, scrub through your video: count the time from the moment the chair appears to the moment the warning voice starts. Do it 5 times.
   - Target: **under 1 second**.

**Done when:** the distance table and speed table are filled in and shared.

### QA-06 · Pitch deck outline (Phase 3)

See section 10 for the slide-by-slide outline. In Phase 3, create the deck with **titles and rough notes only**. Fill in real numbers and screenshots during Phases 4 and 5.

### QA-07 · Demo run sheet + full re-test (Phase 4)

1. Write the run sheet (section 11): who stands where, who says what, in what order, with timings.
2. Rehearse it once with the team at the end of Phase 4.
3. Run **all** checkpoint tabs again (CP1 to CP4) and record results.

### QA-08 · Backup video + final deck (Phase 5)

**Why it matters:** venue Wi-Fi fails all the time at hackathons. A backup video means the presentation still works if the live demo does not.

**Steps**
1. On the demo phone, start the **screen recording** (pull down the quick settings, "Screen record", with sound/media audio on).
2. On your own phone, film the demo user from behind/side, so the judges can see the real situation.
3. Perform the full run sheet once.
4. Stop both recordings. Put them side by side in a simple video editor (CapCut, Canva or similar). Add short captions for each step ("Vehicle warning", "Reading a sign", "Guardian helps").
5. Keep it **under 2 minutes**. Save it on your laptop **and** on a USB stick **and** in the team's shared drive.
6. Put the final numbers and screenshots into the deck.

**Done when:** the video plays offline from your laptop, and the deck is complete.

---

## 7. Your checkpoint job: running the tests every 4 hours

At each checkpoint you are the **Test Lead**. Coder 3 (the "Integration Captain") joins everyone's work and starts the system. **Then you take over:** run the checks, record results and decide pass or fail.

### 7.1 Your steps at every checkpoint

| Time | You do |
|---|---|
| **15 minutes before** | Read the "ready reports" each person posts in chat (what they finished, what slipped). Strike out checks for features that slipped |
| **0 min** | Charge the demo phone. Open your tracker on the checkpoint's tab. Open Postman |
| **When Coder 3 says "ready to test"** | Run the checks **in order**, writing Pass/Fail for each |
| **For every Fail** | Write a bug report (section 8) and say it out loud: "Check 4 failed: the chair warning did not interrupt" |
| **After your list** | Re-run the **previous checkpoint's tab** (regression) |
| **At 30 minutes** | If something is still failing, the team decides: switch it off, or undo it (Coder 3 handles this). You re-test after the change |
| **At the end** | If all required checks pass: go to the GitHub pull request "integration → main" and **approve** it (section 7.8). If not: say clearly **"Not passing"** and why |

**Your answer is final.** If the team says "it's basically working" but a check fails, it fails. You can say: *"Let's switch that feature off and pass the rest."*

### 7.2 Checkpoint 0 (H+1): "Does everything start?" (15 minutes)

| # | Check | Expected |
|---|---|---|
| 1 | Postman: folder **1. Basics → Health check** (Local environment, on the server laptop) | Green; the status says `ok` or `degraded` |
| 2 | Open the app address Coder 1 gives you, add `/user` at the end | A page opens (it can be almost empty) |
| 3 | Same address with `/guardian` | A page opens |
| 4 | On GitHub, branch `qa-docs`, folder `frontend/src/mocks` | Your mock files are there |

### 7.3 Checkpoint 1 (H+4): "The phone talks"

Use the **demo phone** and the **tunnel address** (secure `https://` address).

| # | Check | Expected |
|---|---|---|
| 1 | Open the `/user` page on the phone | Page loads. The phone asks for camera permission once; allow it |
| 2 | Tap the big Start button | You hear "Vision assistant started". The camera starts |
| 3 | Wait 5 seconds | You hear the sample warning: *"Warning. Car approaching from your right, approximately 4 meters away. Please move slightly to your left."* (This is fake data at this stage; that's expected) |
| 4 | Keep listening for 30 seconds | The warning is **not** repeated every second (repeats no more than every few seconds) |
| 5 | Turn the phone's Wi-Fi and mobile data off for 10 seconds, then on | The phone says the connection was lost, then reconnects by itself |
| 6 | Tap Stop | You hear "Vision assistant stopped"; camera turns off |
| 7 | Postman: run folders **1** and **2** (Tunnel environment) | All green (including the 3 "ERROR:" requests getting their expected errors) |
| 8 | Postman WebSocket: hello, ping, broken frame, unknown type (QA-02 Part D) | Replies as in the table in QA-02 |
| 9 | Coder 2 shows their separate camera window on the laptop | Boxes around people; left/ahead/right labels correct when you move; distances roughly right at 2 m and 4 m |

### 7.4 Checkpoint 2 ★ (H+8): "The real thing works" — the most important one

The demo user wears the phone on the chest. Use your tape marks from QA-05.

| # | Situation | Expected |
|---|---|---|
| 1 | Empty corridor, user stands still | **Nothing** is spoken. Screen shows "Path clear" |
| 2 | Person stands on the 2 m mark, straight ahead | *"Person about 2 meters directly ahead."* Said once, then repeated no more than every 6 seconds |
| 3 | Same person steps to 1.5 m | A warning is spoken **immediately** (it is now more urgent) |
| 4 | Put the chair 70 cm in front | *"Stop. Chair about 70 centimeters directly ahead."* It **cuts off** anything else being said |
| 5 | Person stands far left, then far right | The voice says "on your left" / "on your right" correctly |
| 6 | Person walks slowly towards the user from 5 m | On screen the label shows **approaching** within about a second |
| 7 | Coder 3 plays the **vehicle clip** into the system | *"Warning. Car approaching from your right…"* with a distance |
| 8 | Check the debug strip for 1 minute | fps **4 or more**; latency mostly **under 400** |
| 9 | Leave it running for **5 minutes** | No crash, no freezing, voice still working |
| 10 | Postman: folder **3. Detection** with photos 02, 05, 07, 10, 13 | Green; the Console shows sensible objects and directions |
| 11 | Re-run the CP1 tab | Still all passing |

**If CP2 fails, tell everyone clearly.** The rule is: nobody works on bonus features until CP2 passes. Re-test as soon as they say it's fixed; do not wait 4 hours.

### 7.5 Checkpoint 3 (H+12): "The guardian can help"

You need **two devices**: the demo phone (user) and a laptop (guardian). If possible, put them on different networks (phone on mobile data).

| # | Check | Expected |
|---|---|---|
| 1 | Phone: Start the assistant. Laptop: open `/guardian` | The guardian page shows "Arun" and the live camera view (about 2 pictures per second) with boxes |
| 2 | Put the chair 70 cm in front of the user | Within 2 seconds, an alert with a small picture appears on the guardian page |
| 3 | Leave the chair there for 30 seconds | The guardian gets **no more than one alert every 10 seconds** for it |
| 4 | User **presses and holds** the red Emergency button for 1 second | Phone vibrates. Guardian page shows a big red banner with a sound. Phone says *"Your guardian has been notified."* |
| 5 | Guardian clicks **Acknowledge** | Banner closes. Phone says the guardian has seen it and is responding |
| 6 | Refresh the guardian page | Alerts are still listed (they were saved) |
| 7 | Close the app on the phone | Within 10 seconds, the guardian page shows the user as **offline** |
| 8 | With the guardian page open, re-check CP2 checks 4 and 8 | Still fast; chair warning still interrupts |
| 9 | Postman: folder **4. Guardian & alerts** | All green |
| 10 | Re-run the CP2 tab | Still passing |

### 7.6 Checkpoint 4 (H+16): "All features"

This follows the story the judges will see.

| # | Check | Expected |
|---|---|---|
| 1 | Person stands 3 m ahead | *"Person about 3 meters directly ahead."* |
| 2 | Vehicle clip played | Vehicle warning with "move slightly to your left" |
| 3 | User **double-taps** the screen and asks "Is the path clear now?" | A beep, then a sensible spoken answer within about 5 seconds |
| 4 | Hold the "COMPUTER SCIENCE DEPARTMENT" sign in front. Double-tap, say "Read the sign" | The phone reads the sign aloud |
| 5 | Hold the bottle. Double-tap, say "What is this?" | A sensible answer (e.g. "This appears to be a water bottle") |
| 6 | Guardian types "Turn right and continue straight" and sends | Phone says *"Your guardian says: Turn right and continue straight."* within 2 seconds |
| 7 | Guardian uses the microphone button to speak a message | The text appears in the box; after sending, the phone speaks it |
| 8 | User double-taps and says "Emergency" | Same emergency flow as CP3 check 4 |
| 9 | Guardian page map | Shows the user's location; it moves when the user walks outside |
| 10 | Ask Coder 4 to switch off the internet AI (remove the key) and repeat check 3 | You still get a (simpler) spoken answer, not silence or an error |
| 11 | Postman: folder **5. Voice features** (the phone must be streaming for "Ask AI") | All green |
| 12 | Re-run CP2 and CP3 tabs | Still passing |

### 7.7 Checkpoint 5 (H+20): "Final version"

| # | Check | Expected |
|---|---|---|
| 1 | Re-run **all** tabs CP1 to CP4 | All passing (or the failing feature is switched off and not in the demo) |
| 2 | **Network-failure drill:** turn off the venue Wi-Fi on the laptop; Coder 3 switches to the laptop hotspot plan | Time it. The demo is working again in **under 5 minutes** |
| 3 | **No-network fallback:** Coder 2 runs the offline camera demo on the laptop | The laptop speaks warnings with no internet |
| 4 | Play the backup video from your laptop with Wi-Fi off | Plays fully, with sound |
| 5 | Run the full demo (section 11) once, timed | Within the time limit |
| 6 | Any bonus features: tested on their own **and** the full regression still passes | If not, they stay switched off |

### 7.8 How to approve the pull request on GitHub
1. Coder 3 posts a link to the pull request "CP_: …" (from `integration` to `main`).
2. Open it. Read the description: stories included, slipped stories.
3. In the description's "Exit test results" section, Coder 3 leaves boxes for you. Write the pass count and a link to your tracker tab.
4. Click the **Files changed** tab → **Review changes** (green button, top right) → choose **Approve** → write "CP_ tests passed: X/X. Tracker: <link>" → **Submit review**.
5. If tests did not pass: choose **Request changes** instead and list the failing checks.

---

## 8. How to report a problem

### 8.1 How bad is it? (severity)

| Level | Plain meaning | Example | What happens |
|---|---|---|---|
| **S1: Show-stopper** | The core product (camera → warning) doesn't work, or the server crashes | No warnings spoken at all; app freezes | **Everyone stops** and fixes it now |
| **S2: Feature broken** | A feature in this checkpoint doesn't work | Emergency banner doesn't appear | The owner fixes it now, or it is **switched off** for this checkpoint |
| **S3: Annoying** | Works, but not nicely | A word pronounced oddly; a button slightly off-screen | Written down; fixed later |

### 8.2 Bug report template (copy into the "Bugs" tab or a GitHub Issue)

```
Title:      [CP2] Chair warning does not interrupt the person warning
Severity:   S2
Checkpoint: CP2, check #4
Steps:      1. Person stands at 2 m (warning playing)
            2. Push chair to 70 cm
Expected:   "Stop. Chair about 70 centimeters directly ahead." cuts in immediately
Actual:     Chair warning waits until the person sentence ends (about 3 s later)
Evidence:   video clip link / screenshot
Device:     Demo phone, Chrome, mobile data
Owner:      Coder 4 (voice)        ← see section 13
```

**Good bug reports have:** exact steps, what you expected, what happened, and proof (photo, video or Postman screenshot). "It doesn't work" is not a bug report.

---

## 9. Your tracker spreadsheet

Create one Google Sheet called **"Vision Assistant — QA Tracker"** and share it with the team (anyone with the link can view; the team can edit).

| Tab | Columns | Purpose |
|---|---|---|
| **Dashboard** | Checkpoint · Date/time · Passed · Failed · Result (PASS/FAIL) · Notes | One line per checkpoint. The team's quick view |
| **CP0 … CP5** (6 tabs) | # · Check · Expected · Pass/Fail · Notes · Bug link | Copied from section 7 |
| **Bugs** | ID · Title · Severity · Checkpoint · Owner · Status (Open / Fixed / Verified) · Link | Every failure goes here. Only **you** set "Verified" after re-testing |
| **Golden sentences** | Situation · Expected sentence · What the phone said · Match? · Checkpoint | From QA-03 |
| **Distance accuracy** | Object · Real distance (m) · Reading 1 · Reading 2 · Reading 3 · Average · Error % | From QA-05. Formulas below |
| **Speed** | Time · fps · Latency (ms) · Notes | From QA-05 |
| **Seen-to-spoken** | Try # · Seconds | From QA-05 |
| **Photo results** | Photo # · What it shows · What the AI found · Correct? | From Postman detection runs |
| **OCR results** | Photo # · Text on the sign · What was read · Correct? | From CP4 sign tests |

**Formulas for "Distance accuracy"** (if your columns are A to G, starting row 2):
- Average (F2): `=AVERAGE(C2:E2)`
- Error % (G2): `=ABS(F2-B2)/B2` then format the column as **percentage**.
- Average error for the pitch (at the bottom): `=AVERAGE(G2:G11)`

**Formula for "Speed"** (bottom of the tab):
- Average fps: `=AVERAGE(B2:B11)` · Average latency: `=AVERAGE(C2:C11)`

---

## 10. The pitch deck, slide by slide

Aim for **10–12 slides**, about **5 minutes** of talking plus the live demo. Fewer words, bigger pictures.

| # | Slide | What goes on it | Where you get it |
|---|---|---|---|
| 1 | **Title** | "AI-Powered Vision & Guardian Navigation Assistant", tagline *"See the World Through AI"*, team names | — |
| 2 | **The problem** | A walking stick tells you something is there, but not **what** it is, **how far**, **which side**, or **whether it's moving** | Vision PDF section 2 |
| 3 | **Our idea in one sentence** | *"An AI-human collaborative assistant: AI sees, measures and speaks; a guardian steps in when needed."* | Vision PDF section 25 |
| 4 | **How it works** | Simple picture: Phone camera → AI recognises objects → direction + distance → danger check → voice warning → guardian dashboard | Ask Coder 3 for the architecture sketch |
| 5 | **Live demo** | Just the word "Live demo" (switch to the phone/projector here) | Section 11 |
| 6 | **What makes it smart** | Not "object detected" but *"Car approaching from your right, 4 meters away. Move left."* Prioritises danger, doesn't talk constantly | Vision PDF section 20 |
| 7 | **Human in the loop** | Guardian sees the live view and can speak to the user. Emergency button and voice command | Screenshots from CP3 |
| 8 | **Measured, not guessed** | Your **distance accuracy table** (average error %), **speed** (fps, latency, seen-to-spoken time) | Your tracker, QA-05 |
| 9 | **Privacy by design** | Camera images are **not stored**; only alerts are saved | `API_CONTRACTS.md` section 10, ask Coder 3 to confirm |
| 10 | **Tech stack** | Logos or names: React, FastAPI, YOLOv8, OpenCV, Gemini, Tesseract, Supabase | Team plan |
| 11 | **What's next** | Smart glasses, stairs and door detection, indoor navigation, Tamil voice, offline mode | Vision PDF section 24 |
| 12 | **Thank you / Questions** | Team names, a QR code to the repo or demo video | — |

**Honesty rules for the deck** (judges respect this):
- Always say **"approximate distance"**, never "exact".
- Don't claim stairs, doors, potholes or poles are detected unless the team confirms that feature works. Put them in "What's next".
- Use **your measured numbers**, even if they're not perfect. "Average distance error 18% up to 5 m" is believable; "100% accurate" is not.

**Prepare answers to likely judge questions** (write them in the speaker notes):
- *How do you measure distance with one camera?* → "We know the typical real height of each object; the smaller it looks, the further it is. We calibrated it for this phone."
- *What if the AI is wrong?* → "That's why there's a guardian, and the system says when it's unsure."
- *Does it need internet?* → "The warnings run on our server. Questions use the internet AI, with a simple offline answer if it's unavailable."
- *Privacy?* → "We don't store camera images."
- *Cost?* → "It runs on an ordinary phone; the AI model is free and open source."

---

## 11. The live demo run sheet

Based on the vision document's campus scenario (section 17). Total about **3–4 minutes**.

### 11.1 Roles

| Role | Who | Where |
|---|---|---|
| **Narrator** | You (Member 5) | Front, facing the judges |
| **Demo user** | One coder, blindfolded, phone on chest | Walking area in front of the judges |
| **Guardian** | One coder | At the laptop connected to the projector (guardian dashboard on screen) |
| **Props person** | One coder | Moves the chair, holds the sign, plays "person ahead" |
| **System operator** | Coder 3 | At the server laptop; plays the vehicle clip; ready with fallbacks |

### 11.2 Script

| Step | Time | Narrator says | What happens | Judges should notice |
|---|---|---|---|---|
| 0 | 0:00 | "Our user can't see. The phone on their chest is their eyes." | Demo user taps Start. Phone: "Vision assistant started" | The blindfold; the guardian screen shows the live camera |
| 1 | 0:20 | "Someone is standing ahead." | Props person stands 3 m ahead. Phone: *"Person about 3 meters directly ahead."* | Distance + direction in a natural sentence |
| 2 | 0:45 | "Now something dangerous." | Props person pushes the chair to 70 cm. Phone: *"Stop. Chair about 70 centimeters directly ahead."* | Urgent warning interrupts; red box on screen |
| 3 | 1:10 | "On a road, vehicles matter most." | Operator plays the vehicle clip. Phone: *"Warning. Car approaching from your right…"* | Direction of approach + advice to move |
| 4 | 1:40 | "The user can ask questions." | User double-taps: "Is the path clear now?" Phone answers | Conversation with the AI |
| 5 | 2:05 | "And read signs." | Props person holds the department sign. User: "Read the sign." Phone reads it | Reading text aloud |
| 6 | 2:30 | "When the AI isn't sure, a human helps." | Guardian types "Turn right and continue straight." Phone: *"Your guardian says: …"* | Human in the loop |
| 7 | 2:55 | "And in an emergency…" | User holds the Emergency button. Guardian screen: red banner + sound. Guardian clicks Acknowledge. Phone confirms | Safety net |
| 8 | 3:20 | "AI sees, understands, speaks, and a guardian is always one tap away." | Back to slides | — |

### 11.3 If something goes wrong during the demo
- **Stay calm and keep talking.** Say: *"Live demos at hackathons are brave. Let me show you the recording."*
- Small glitch (one sentence missing): just move to the next step.
- Phone or network fails: operator gives you a thumbs-down → switch to the **backup video** immediately.
- Never debug in front of the judges.

---

## 12. Demo-day checklist

**30 minutes before**
- [ ] Demo phone and your phone charged above 80%; power bank ready
- [ ] Phone: Do Not Disturb **on**, volume at **maximum**, screen auto-lock **off**, other apps closed
- [ ] Phone page open on the **current** tunnel address, camera permission allowed
- [ ] Guardian laptop on the projector, dashboard open, sound **on**
- [ ] Backup video on your laptop desktop **and** USB stick; tested with Wi-Fi off
- [ ] Deck open on the presentation laptop, starting at slide 1
- [ ] Props ready: chair, signs, bottle, blindfold, chest strap
- [ ] Walking area marked: a tape mark at 3 m for "person ahead"

**10 minutes before**
- [ ] One quick test: Start → person ahead → warning heard
- [ ] Everyone knows their role (section 11.1)

**After**
- [ ] Thank the judges. Note any questions you couldn't answer, for the team.

---

## 13. Who to ask for what

| If the problem is… | Ask | Their branch |
|---|---|---|
| Phone screens, buttons, guardian page, map, camera won't start | **Coder 1** (Frontend) | `frontend-ui` |
| Wrong objects, wrong distance or direction, boxes in the wrong place | **Coder 2** (AI Vision) | `ai-core` |
| Server down, Postman errors 500/503, tunnel address, alerts not saved | **Coder 3** (Backend), also the Integration Captain | `backend-api` |
| Voice: wrong words, wrong order, not speaking, questions, sign reading | **Coder 4** (Voice & Integrations) | `voice-ocr` |
| Not sure who | Coder 3; they'll route it | — |

**Best times to ask:** between checkpoints, after a coder has just pushed their work. **Avoid** interrupting Coder 2 during Phases 1 and 2. They are on the critical path; post in chat instead and they'll answer when they pause.

---

## 14. Your golden rules

1. **Always check you're on `qa-docs`** before uploading anything to GitHub. Never `main`.
2. **Test on the real demo phone**, over the real tunnel address. A laptop test is not enough.
3. **Write it down.** A result that isn't in the tracker didn't happen.
4. **A failing check is a failing check.** Your job is to be honest, not popular. Offer the solution: "switch it off and pass the rest".
5. **Re-test old things every time.** New features often break old ones.
6. **Proof beats opinion.** Screenshot, video, Postman result.
7. **Measure, don't guess.** Your numbers make the pitch believable.
8. **Charge everything, always.**
9. **The backup video is your insurance.** Record it before you think you need it.
10. **You know the product best from the outside.** If something confuses you, it will confuse the judges. Say so.
