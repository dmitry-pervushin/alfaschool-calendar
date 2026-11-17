# Alfa School Calendar for Home Assistant - import your Alfa School calendar

**English** · [Русский](README.ru.md)

![Integration icon](custom_components/alfaschool/brand/icon.png)

## Requirements

- Home Assistant **2026.11 or later**.
- An account at [my.alfaschool.ru](https://my.alfaschool.ru/).
- Internet access from Home Assistant to the school website.

This is an independent custom integration, not an official Alfa School product.

## Installation

### HACS

[HACS](https://hacs.dev/) must be installed.

1. Open HACS and search for **Alfa School Calendar**.
2. Open the integration and select **Download**.
3. Restart Home Assistant.
4. Add the integration as described under [Setup](#setup).

#### If the integration does not appear in search

Add the repository manually:

1. Open **HACS → ⋮ → Custom repositories**.
2. Enter the following URL in the **Repository** field:

   ```text
   https://github.com/dmitry-pervushin/alfaschool-calendar
   ```

3. Select **Integration** as the type and select **Add**.
4. Return to HACS search and follow the installation steps above.

For more information, see the [HACS custom repository documentation](https://hacs.dev/docs/faq/custom_repositories/).

### Manual installation

1. Download `alfaschool-integration.zip` from the
   [latest release](https://github.com/dmitry-pervushin/alfaschool-calendar/releases/latest).
2. Extract the archive into your Home Assistant configuration directory.
   The manifest should be at `custom_components/alfaschool/manifest.json`.
3. Restart Home Assistant and continue with [Setup](#setup).

## Setup

1. Go to **Settings → Devices & services → Add integration → Alfa School**.
2. Enter your school login and password. The student's name is read automatically
   from their profile. Choose an update interval in hours: `24` (the default),
   `8`, `4`, or any whole number from 1 to 24.
   Set it to `0` for **manual updates only**.

Each account gets its own calendar, named **Alfa School — Name from profile**.
Names keep the order used on the school website. If no name is available,
the login is used instead. To connect another account, add another instance
of the integration. Login and access to the current month's schedule are
checked before saving your settings.

Home Assistant creates the `entity_id` from the calendar name when it is first
added. For example, `Dmitry` becomes `calendar.alfa_school_dmitry`, and `Anna`
becomes `calendar.alfa_school_anna`. Home Assistant transliterates Cyrillic names.
If names match, Home Assistant adds a suffix such as `_2`. Accounts, sessions,
and lessons remain separate.

You can change the student's name under **Configure**. Clear the field to use
the profile name again. Existing accounts without a saved profile name will
have it detected on the first successful load after updating. A name you enter
manually takes priority.

Renaming a calendar preserves its existing `entity_id` and `unique_id`, so
existing automations keep working. Previously installed calendars also keep
their entity IDs. Names and entity IDs you customize in Home Assistant are
preserved.

## Updating the integration

If installed through HACS, open **Alfa School Calendar**, install the available
update, and restart Home Assistant.

For a manual installation, download the ZIP from the new release, replace
`custom_components/alfaschool`, and restart Home Assistant. Keep the existing
integration entry in Home Assistant settings.

## Your schedule in Home Assistant

Lessons appear in Home Assistant's **Calendar** section. Each lesson includes
the subject, teacher, start time, and duration. Times are displayed in your
Home Assistant time zone.

By default, the integration loads lessons from the past 30 days and the next
180 days. Browse to another period to load the months you need. In manual
update mode, refresh the calendar manually after browsing to a different period.

Book, reschedule, and cancel lessons in your Alfa School account. Those changes
will appear in Home Assistant after the calendar refreshes. Blocks marked
“Busy period” are not shown as lessons.

### When your schedule refreshes

Your schedule loads when Home Assistant starts, then refreshes at your chosen
interval. For example, `4` means every four hours and `24` means once a day.
Change this under **Settings → Devices & services → Alfa School → Configure**.

Choose `0` to turn off automatic updates. After the initial load when Home
Assistant starts, the schedule will refresh only when you request it.

Rescheduled and canceled lessons appear after the next refresh. To see changes
sooner, refresh the calendar manually.

### Refreshing your calendar manually

Go to **Developer tools → Actions**, select **Update entity**
(`homeassistant.update_entity`), choose your Alfa School calendar, and run
the action.

You can also use this action in a dashboard button or an automation:

```yaml
action: homeassistant.update_entity
target:
  entity_id: calendar.alfa_school_dmitry
```

Replace `calendar.alfa_school_dmitry` with your calendar's entity ID.

### If your schedule is unavailable

If the school website cannot be reached, the calendar becomes temporarily
unavailable. Check your internet connection and try refreshing it manually.
If automatic updates are enabled, the integration will retry on its own.

If your password changes, Home Assistant will ask you to sign in again.
There is no need to remove the integration or set up your calendar from scratch.

## A reminder 15 minutes before a lesson

```yaml
alias: Alfa School lesson reminder
triggers:
  - trigger: calendar
    entity_id: calendar.alfa_school_dmitry
    event: start
    offset: "-00:15:00"
actions:
  - action: persistent_notification.create
    data:
      title: Lesson starting soon
      message: "{{ trigger.calendar_event.summary }}"
mode: parallel
```

Schedule changes are detected when the calendar refreshes. With a 24-hour
interval, a last-minute reschedule may take up to a day to appear in Home Assistant.

## Credentials

Your login and password are entered in Home Assistant and stored in its standard
configuration entry. The integration connects only to `https://my.alfaschool.ru`,
does not log your password, and does not publish your schedule through `/local/`.
Cookies are kept in memory in a separate session for each account. Account access
is used only to sign in and read schedule pages.

To remove the integration, go to **Settings → Devices & services → Alfa School
→ Delete**. Unloading the integration stops updates and closes the account session.

## License

[BSD Zero Clause (0BSD)](LICENSE).
