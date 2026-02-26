# Parish Bulletin Aggregator

> If you want to know what's going on, the ground truth is the bulletin.

# Workflow

## 1. Scrape PDFs
PDFs can be gathered from:
https://parishesonline.com/organization/epiphany-church
https://discovermass.com/church/st-patrick-bloomington-il/#bulletins
https://discovermass.com/church/st-patrick-church-of-merna-bloomington-il/#bulletins
https://discovermass.com/church/st-mary-bloomington-il/#bulletins

We want to download every bulletin on these pages after the last collected date as a .pdf and collect this data at this stage:
- the url the bulletin can be accessed from
- the date of the bulletin

Ideally this step is done purely with a python script.

## 2. Process PDFs

Now PDFs should be fed into an LLM (in this case we will use Claude Code). The LLM should be instructed to generate a list of all events in the bulletins. Each event object should have:
- `location`
- `datetime` (a singular machine-parsable datetime that is used to place it on the calendar)
- `time_desc` (a description of the time, e.g. 'Febuary 6, 6-9 PM'; some events could have weird descriptions of the time)
- `details` (the details of the event listed in the bulletin)
- `bulletin_url` (the URL of the bulletin this was found in)
- `bulletin_page` (the page of the bulletin this was found in)
- `id` (a sequential identifier to distinguish this from other events) (this won't actually get populated yet but will be important later)
- `type` (a string denoting type. if it's just a regular event, it'll be `misc`; it could also be `mass` or `adoration` or `confession`)
- `cancelled` (a boolean flag denoting that an event existed and was cancelled)

Usually masses and adoration and confession are listed as ranges. You can put mass intentions or other notes in the `details` section. Create unique event objects for each day. Don't record that they recur into the future.

## 3. Data Merge

Here we again us an LLM to merge what we gathered from the bulletin with previously known information. This means we:
- Add new events
- Mark events as cancelled if they are cancelled (if they are simply not spoken of, don't do anything)
- Merge events that appear to be the same. If more information is given, merge/update the description with the new data.
- Remove events that happened in the past.

Will have to manage `id`s. `id` should just continuously increment, never going backwards.

## 4. Publish through Hugo

We need a website to display this data. The website should:
- Be made with Hugo as a static site generator
- Have a page for "events" (in general) that shows all of the `misc` events
- Have a page for mass that shows all the `mass` events. Same for `adoration` and `confession`.
- Each event should be listed in chronological order based on `datetime`. 
- Details for each event should be listed; `location`, `time_desc`, `details`.
- If it is `cancelled` that should be indicated (do nothing special if it's still on)
- Should provide a proof link that goes to `bulletin_url` (preferably even going to `bulletin_page`).
- Should provide a detailed link that goes to `/event/12345` (where 12345 is the `id`).
 - This also means that a page for this event would need generated

Ideally this step is done purely with a python script.