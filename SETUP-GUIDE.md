# Money Planner – setting it up

There are three parts:

- **Part A:** you put the app online (about 15 minutes, done once).
- **Part B:** you try it on your Android phone.
- **Part C:** you put it on her iPhone, together.

Her money information is only ever saved on her own phone. What goes on GitHub is just the app itself. It contains no personal details.

---

## Part A – Put the app on GitHub Pages (on a computer)

1. **Unzip** `money-planner.zip`. You get a folder with these items:
   `index.html`, `manifest.webmanifest`, `sw.js`, `.nojekyll`, `SETUP-GUIDE.md`, and two folders called `fonts` and `icons`.
   (`.nojekyll` may be hidden on your computer. That's fine; see step 4.)
2. Go to **github.com** and sign in as **MrSpongeHead**.
3. Make a new repository:
   - Click **+** (top right), then **New repository**.
   - **Repository name:** `money-planner`.
   - Choose **Public**. Free GitHub accounts can only use Pages with public repositories.
   - Tick **Add a README file**, then click **Create repository**.
4. Upload the files:
   - On the repository page, click **Add file → Upload files**.
   - Open the unzipped folder, select **everything inside it** (including the `fonts` and `icons` folders), and drag it onto the GitHub page. Chrome and Edge keep the folders.
   - If `.nojekyll` didn't come across because it was hidden, don't worry. The app works without it.
   - Scroll down and click **Commit changes**.
5. Turn on Pages:
   - Click **Settings** (top of the repository), then **Pages** (left-hand menu).
   - Under **Build and deployment → Source**, choose **Deploy from a branch**.
   - Under **Branch**, choose **main** and **/ (root)**, then click **Save**.
6. Wait a few minutes, then refresh the Pages settings page. It shows the app's address, which should be:
   **https://mrspongehead.github.io/money-planner/**

**Check:** open that address on your computer. You should see "Put the app on my phone".

---

## Part B – Try it on your Android phone

1. Open the address in **Chrome** on your phone.
2. Tap **Install the app** if you see that button. If not, tap the **⋮** menu, then **Add to home screen** or **Install app**.
3. Open **Money Planner** from the new icon.
4. On the "Setting up" screen, tap **Just looking? Try it with example data**. This fills the app with made-up figures, the same as the mock-ups, so you can try every screen.
5. When you've finished testing: **Today → ⚙ Settings → Backup & privacy → Delete all my money information.**

**Tip for testing on a computer:** add `?today=2026-11-28` to the end of the address to pretend it's a different day, for example pay day or the end of the month. Only do this in a normal browser tab, not in the installed app.

---

## Part C – Put it on her iPhone (together)

1. Send her the address in a message, or open it on her phone yourself. It must open in **Safari**.
2. In Safari, tap the **Share** button (a square with an arrow pointing up).
3. Scroll down, tap **Add to Home Screen**, then **Add**.
4. Close Safari and open **Money Planner** from the new icon.
   **Always use the icon.** The app shows a picture guide if it's opened in Safari instead. This matters because iPhones can delete website data after seven days of using Safari without visiting the site. Apps added to the home screen are treated separately.
5. Go through **Setting up** together. Have her bank statement and card statements to hand. It saves as you go, so you can stop and carry on another day.
6. The short tour starts by itself at the end. She can replay it any time from Settings, or from any **?** button.
7. Make a first backup: **⚙ Settings → Backup & privacy → Back up now**. On iPhone this opens the share sheet, so you can save the file to Files or iCloud Drive, or email it to yourself.

---

## Updating the app later

When I send you a new version:

1. In the repository, click **Add file → Upload files** and drag in the new files. Files with the same name are replaced.
2. Click **Commit changes**.
3. Wait a few minutes. The next time she opens the app with internet, it gets the new version. If it doesn't, close the app fully and open it again.

**Her information is not affected by updates.** It stays on her phone.

---

## Good to know

- **Offline:** after the first open, the app works without internet.
- **Backups:** these are the only copy outside her phone. The app reminds her every two weeks. Keep backup files somewhere safe, because they contain her money details.
- **Reminders:** these show on the Today screen when she opens the app. The app can't send pop-up notifications.
- **New phone:** install the app on the new phone, then use **Backup & privacy → Restore from a backup**.
- **PIN lock:** this stops rules and limits being changed by accident. It isn't strong security. Anyone holding her unlocked phone could still see her figures.
- **Bank balance:** the app can't see her bank. She types her balance once (Today → "Add my bank balance"), the app estimates it from then on, and the weekly check-in asks her to confirm or correct it. Money in pots and the ISA is not counted in it.
- **Pay days and bank holidays:** each income can be set to arrive the working day before or after a weekend or bank holiday. The app includes the official UK bank holiday dates up to the end of 2028 and warns when it needs a newer version.
- **Interest figures:** these are estimates (balance × APR ÷ 12). Statements can differ a little.
