# InkServices
The idea behind inkservices is the ability to create small interactive services that run on the host server and allow the user to interact with their E-Ink shelf tags in daily use.


## Example use-cases
I have a couple of examples that i want to implement later on, they show what the idea is.

### App idea 1: Pill tracker
It's a tracking app for the anticonception pill for women. show all pills that need to be taken for the whole month in a grid on one side of the screen and the date and time when the last pill was taken. When the user has taken a pill they should tap their phone against the tag and it will log the date and time and update the display.

### App idea 2: Weather, moon phases, waste/recycling tracker or commute
Use generically available API's to get the weather, the phase of the moon or the expected time of your commute
there is no actual interaction, but has a configurable interface.

### App idea 3: Calendar
The tag shows either an overview for the day or week from your agenda

### App idea 4: TODO list or chore tracker
A Simple to-do list and using NFC the user can cross of items or log when they were done

### App idea 5: Messageboard
Using NFC, the user can leave messages on the screen for other people in the house

## Implementation
I want the user to easily be able to write these apps in python. there should be a ready-to-go API/library that the user can use to set up the app and run it and select what tag/tags the app should run off of. The NFC on the tag should redirect to the web interface for the app. the web interface should be simple to set up using python. Basic functionality like a list of buttons with callbacks to functions in the app itself. for examnple the tag just redirects to the server xxx.com/<TAG_ID> and show the available buttons for interaction, or for example a text field where you can enter text.

I want the layout to be handled by AI and an easy iterative chatbot interface to create the layout for the tags. And maybe have an agent also handle the backend of the app, but leave the option for manual coding open.

## Server UI
The server should have an added tab called 'Apps' where you can select what apps are running, interact with their data and manage the tags that run the app. Then when the user enables development mode in the settings, another tab should appear where you have an integrated simple development ui where you can create a new app and develop it's functionality.


### App management
i want to easily be able to clone a git repo from github and that should install the app. If possible, i would like to have the option for the user to validate the safety of the app using an API call to an AI that checks whether there are any safety issues with the app before running it. 


### Development
The development ui should have a 'virtual tag' that the app is running with to test everything. I want to be able to switch between front-end design, app description and info and version management, backend development, finally debugging and statistics.


