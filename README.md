Mom, can we have Mattermost?

Mom: We have Mattermost at home.

The Mattermost at home:

![Skype Logo](./imgs/skype.png)

![Smurf Fine](./imgs/smurf.png)

# MiniMost

The two hardest problems in computer science are:

&emsp;~~1. Cache invalidation~~

&emsp;~~2. Naming things~~

1. Communication
2. Convincing others its communication

## FAQ

Is it well written?

> No

Was it vibe coded in a weekend?

> Maybe

Is it not Skype?

> Yes

## Description 

MiniMost is lightweight, self-host collaboration platform for messaging. The goal of this project is to be dependant light, runnable by users without root, and accessible in the browser.

To launch the server all that is needed is python3 and flask. That's it. For the database sqlite is used meaning no external database is required.

## Features

- [x] Channels
- [ ] Editable messages
- [x] Separate users
- [x] User presence
- [x] Persistent messages
- [x] Message search
- [x] Embedded images 
- [ ] Picture previews
- [x] User sign up
- [x] Direct messages
- [x] Group messages
- [ ] Password protected database
- [ ] Password reset 
- [x] Read protected databases 
- [ ] Sort users by most recently messaged 
- [ ] Autocomplete username for new DMs 
- [x] Clickable URLs 
- [ ] Bold/Underline/Italic modifiers
- [ ] Typing indicators
- [ ] New message indicators
- [ ] Date/time stamps on messages  

## Real FAQ

Are my messages secure?

> There is no end to end encryption for messages. Each user gets their own sqlite database to prevent intermixing of messages. These databases are files on the file system and are not encrypted but are not read accessible to all users. There is an additional auth database which stores all users usernames and a sha256 hash of their passwords meaning no passwords are stored plain text.This does mean without a password reset mechanism that any user who forgets their password wouldn't be able to get back into their account.

This is great, but could it also have feature x?

> Yeah! The great part of having the source code for this is that edits can be made! Feel free to create a PR with some proof showing the new feature works and it can be merged and redeployed.

I really want feature x but don't want to put in the time to figure out how to implement it. Can you add it?

> Its more likely to get done if you're able to add the features you want, but if not feel free to add it to the features list in the features sections. It *might* get implemented at some point.

