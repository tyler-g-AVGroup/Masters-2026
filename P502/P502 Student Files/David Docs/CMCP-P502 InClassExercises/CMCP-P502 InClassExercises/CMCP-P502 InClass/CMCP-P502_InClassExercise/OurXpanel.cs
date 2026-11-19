// using statements related to Crestron programming
using Crestron.SimplSharp;
using Crestron.SimplSharpPro;
using Crestron.SimplSharpPro.DeviceSupport; 
using Crestron.SimplSharpPro.UI;


namespace CMCP_P502_InClassExercise
{
    /// <summary>
    /// The logic required to implement the xpanel we will be using for the in class examples
    /// </summary>
    internal class OurXpanel
    {
        #region ++++ fields ++++
        // regions are used to create collapsible areas of code
        // a field is a variable that stores data directly inside a class, fields are frequently private and only accessible within a class

        // a field to hold a reference to the control system.
        // This allows you to break things out in a class that otherwise would need to be in the 'main' control system class
        ControlSystem myControlSystem;

        // declaration of the MessageWindow class 
        // this is a class created to format and drive the message window on the xpanel
        MessageWindow myMsgWindow;

        // declaration of the xpanel itself
        // notice the ? after the class name.  This is a signal to the compiler that we understand this could be null
        XpanelForHtml5? myPanel;



        #endregion

        //---------------------------------------------------------------------------------------------------------------------------

        #region ++++ constructors ++++ 
        // constructors are called when a new instance of a class is created

        // The constructor is public because the calling class needs access to it
        public OurXpanel(ControlSystem controlSystem)
        {
            // it is highly unlikely that this could be run with controlSystem being null,
            // however the possible null condtion still needs to be handled
            // In this case, we chose to throw a null reference exception, which will stop the constructor from proceeding forward
            // Also notice that when an if statement executes a single line of code, the { } are optional
            if (controlSystem == null) throw new NullReferenceException("Control System is null");

            // sets the myControlSystem property to point to the control system that is passed in to the constructor
            myControlSystem = controlSystem;

            // check to make sure the control system supports ethernet 
            // In C# we do not define a specific model control system, program could be run on any model
            if (myControlSystem.SupportsEthernet)
            {
                myPanel = new XpanelForHtml5(0x03, myControlSystem);        // creates a new xpanel with an IP-ID of 03, associated with the current control system
                myPanel.SigChange += new SigEventHandler(MyPanel_SigChange);    // registers the method MyPanel_SigChange to be called when there is a signal change event 
                myPanel.OnlineStatusChange += new OnlineStatusChangeEventHandler(MyPanel_OnlineStatusChange);   // registers the method MyPanel_OnlineStatusChage to be called when the panel comes online
                myMsgWindow = new MessageWindow(myPanel.StringInput[1], 30);    // creates a new MessageWindow that outputs to serial join 1 on the xPanel and has a height of 23 lines of text

                // compound statement the both registers the xpanel and checks to see if the registration was successful
                // calling the method myPanel.Register() returns a value of the type eDeviceRegistrationUnRegistrationResponse which is an enumeration
                // if the return value is not eDeviceRegistrationUnRegistrationResponse.Success, we write an error to the log file
                if (myPanel.Register() != eDeviceRegistrationUnRegistrationResponse.Success)
                {
                    ErrorLog.Error("Error registering xpanel: {0}", myPanel.RegistrationFailureReason.ToString()); // write a message to the log file.
                                                                                                                   // myPanel has a property RegistrationFailureReason which is an enumeration
                                                                                                                   // calling .ToString() converts the enumeration value to text for the log entry 
                }
            }
            else
            {
                ErrorLog.Error("Control System does not support ethernet"); // write a message to the log that the control system does not support ethernet
                myMsgWindow = new MessageWindow();  // creates a "dead head" message window.
                                                    // This was done as one option of how to handle the possibility of exiting the constructor with myMsgWindow being null
                                                    // Otherwise it would be necessary to add a null test everytime myMsgWindow is referenced.

            }
        }


        #endregion

        //---------------------------------------------------------------------------------------------------------------------------

        #region ++++ events ++++
        // events provide a way for a class to call methods in other classes without having to know what the other calling classes 
        // or methods are.  This is accomplished by the other class subscribing to this class' event.

        /// <summary>
        /// Event handler for button 1 press/release events
        /// </summary>
        public event EventHandler<PressStateEventArgs>? Button1Press;

        /// <summary>
        /// Event handler for button 2 press/release events
        /// </summary>
        public event EventHandler<PressStateEventArgs>? Button2Press;

        /// <summary>
        /// EventArgs for Button Press events
        /// </summary>
        public class PressStateEventArgs : EventArgs
        {
            public PressStateEventArgs() { }
            public PressStateEventArgs(bool state)
            {
                ButtonPressed = state;
            }

            /// <summary>
            /// True if button press, false if button release
            /// </summary>
            public bool ButtonPressed { get; set; }
        }

        /// <summary>
        /// Event handler for Online / Offline events
        /// </summary>
        public event EventHandler<OnlineEventArgs>? OnlineStatusChange;

        /// <summary>
        /// Event Args for the OnlineStatusChange event handler
        /// </summary>
        public class OnlineEventArgs : EventArgs
        { 
            public OnlineEventArgs(bool online) 
            { 
                Online = online;
            }

            /// <summary>
            /// True if the xPanel is online
            /// </summary>
            public bool Online { get; set; }    
        }


        #endregion

        //---------------------------------------------------------------------------------------------------------------------------

        #region ++++ properties ++++
        // properties function similar to fields, but add the ability to control access and execute logic when setting or getting data
        // properties are typically used to manage access to private data from outside the class


        /// <summary>
        /// Feedback state for Button 1
        /// </summary>
        public bool Button1fb
        {
            get
            {
                if (myPanel != null)
                {
                    return myPanel.BooleanInput[1].BoolValue;
                }
                else { return false; }
            }
            set
            {
                if (myPanel != null)
                {
                    myPanel.BooleanInput[1].BoolValue = value;
                }
            }
        }


        /// <summary>
        /// Feedback state for Button 2
        /// </summary>
        public bool Button2fb
        {
            get
            {
                if (myPanel != null)
                {
                    return myPanel.BooleanInput[2].BoolValue;
                }
                else { return false; }
            }
            set
            {
                if (myPanel != null)
                {
                    myPanel.BooleanInput[2].BoolValue = value;
                }
            }
        }

        /// <summary>
        /// True if first time programming in C#
        /// </summary>
        public bool FirstExperienceCSharp 
        {
            //get; 
            set
            {
                if (myPanel != null)
                {
                    if (value)
                    {
                        myPanel.StringInput[4].StringValue = "This is my first time programming in C#!";
                    }
                    else
                    {
                        myPanel.StringInput[4].StringValue = "I have programmed in C# before.";
                    }
                }
            }
        }

        /// <summary>
        /// The Student's Name
        /// </summary>
        public string StudentName 
        {
            //get;
            set 
            {
                if (myPanel != null) myPanel.StringInput[2].StringValue = value;
            }
        }

        /// <summary>
        /// Number of Masters the student has atttended
        /// </summary>
        public int YearsAttended 
        {
            //get; 
            set 
            {
                if (myPanel != null)
                {
                    if (value < 0) 
                        myPanel.StringInput[3].StringValue = "";
                    else
                        myPanel.StringInput[3].StringValue = String.Format("{0}", value);
                }
            } 
        }

        #endregion

        //---------------------------------------------------------------------------------------------------------------------------

        #region ++++ public methods ++++
        //  methods that are accessible from outside of the class


        /// <summary>
        /// Prints a message to the message window
        /// </summary>
        /// <param name="message">The message to print</param>
        public void PrintMessage(string message)
        {
            if (message != null)    // check to make sure the message exists
            {
                    myMsgWindow.Add(message);   // add the message to the message window
            }
        }

        #endregion

        //--------------------------------------------------------------------------------------------------------------------------
    
        #region ++++ private methods ++++
        //  methods that are only accessible from within the class itself
 
       

        // Method that is called when the xpanel goes online.
        // The declaration of the method has to match what was defined in the calling class.  This is accomplished using a delegate statement. 
        private void MyPanel_OnlineStatusChange(GenericBase currentDevice, OnlineOfflineEventArgs args)
        {   
            // when the xpanel comes online
            if (myPanel != null)    // check to make sure myPanel is not null
            {
                myMsgWindow.Clear();    // clear the contents of the message window
                myMsgWindow.Add( "XPanel Online");  // add a line of text to the message window
                if (OnlineStatusChange != null)    // check to see if there are any methods registered to OnlineEvent
                {
                    OnlineStatusChange.Invoke(this, new OnlineEventArgs(args.DeviceOnLine));  // at least one method is registered, so call them.
                }
            }
        }


        // Method that is called whenever there is a signal change reported by the xpanel
        // when myPanel calls the method it will provide two pieces of information the BasicTriList for the calling device 
        // and SigEventArgs for the signal that triggered the method being called.
        private void MyPanel_SigChange(BasicTriList currentDevice, SigEventArgs args)
        {
            //  First step - filter the sig event by type using a switch / case
            switch (args.Sig.Type)  
            {
                case eSigType.Bool:     //digital value from the UI
                    
                    // Second step - filter by join number
                    switch (args.Sig.Number)  //switch case on join number
                    {
                        case 1: // button 1
                            // Trigger the Button1Press event if someone has registered to it.
                            if (Button1Press != null) Button1Press.Invoke(this, new PressStateEventArgs(args.Sig.BoolValue));
                            break;

                        case 2: // button 2
                            // Trigger the Button2Press event if someone has registered to it.
                            if (Button2Press != null) Button2Press.Invoke(this, new PressStateEventArgs(args.Sig.BoolValue));


                            /*
                            // doing the same timer callback here
                            if (args.Sig.BoolValue) // true (button pressed)
                            {
                                currentDevice.BooleanInput[2].BoolValue = true;     // set digital feedback join 2 high
                                PrintMessage("Button 2 Set");   // print a message to the message window - notice public methods can be called internally as well
                                startTimer();   // start our 5 second timer
                            }
                            */
                            break;
                    }
                    break;
                case eSigType.UShort:   //analog value from the UI
                    break;
                case eSigType.String:   // text entry from the UI
                    break;
            }

        }

        //-----------------------------------------------------------


        // definition of a CTimer for us to use 
        CTimer? button2Timer;

        // method to call to start the timer
        // we could have just put this logic in the button two case of the switch statement, but if there are a lot of buttons defined, that would make it a really long switch/case
        void startTimer()
        {
            if (button2Timer == null)   // if the CTimer is null, create a new CTimer
            {
                button2Timer = new CTimer(button2Callback, 5000);
            }
            else    // if the CTimer already exists, call it again 
            {
                button2Timer.Reset(5000);
            }
        }

        // method that gets called when the CTimer expires  
        // CTimer supports optionally passing an object to the callback method, so we have to match the definition of the delegate
        void button2Callback(object? o)
        {
            if (myPanel != null)    // check to make sure myPanel is not null - a good thing to do since it's been 5 seconds
            {
                myPanel.BooleanInput[2].BoolValue = false;  // set digital feedback join 2 low
                PrintMessage("Button 2 Cleared");   // print a message to the message window
            }
        }

        #endregion

    }
}
