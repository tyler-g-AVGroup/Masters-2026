using Crestron.SimplSharp;
using Crestron.SimplSharpPro;


namespace CMCP_P502_InClassExercise
{
    /// <summary>
    /// Formatting for a multi-line message window.  When the max number of lines is reached, the text scrolls up, removing the top line.
    /// </summary>
    internal class MessageWindow
    {
        #region ++++ fields ++++

        // creation of a list of strings to hold the individual text entries
        private List<string> messages = new List<string>();

        // the maximum number of lines to display
        private int maxLines;

        // a reference to the serial feedback join for the message window
        private StringInputSig? outputSig;
        #endregion

        #region ++++ Constructors ++++

        /// <summary>
        /// MessageWindow Constructor to use for a real message window
        /// </summary>
        /// <param name="destination">the serial feedback join to use for the window</param>
        /// <param name="MaxLines">the maximum number of lines of text the window will hold</param>
        public MessageWindow(StringInputSig destination, int MaxLines)
        {
            outputSig = destination;
            maxLines = MaxLines;
        }

        /// <summary>
        /// constructor for a placeholder list
        /// </summary>
        public MessageWindow()
        {
            maxLines = 0;
            outputSig = null;
        }

        #endregion

        #region ++++ Public Methods ++++

        /// <summary>
        /// Add a message to the message window
        /// </summary>
        /// <param name="message">the message to add</param>
        public void Add(string message)
        { 
            messages.Add(message);  // add the messgae text to the end of the list

            if (messages.Count > maxLines)  // if the list is now longer than the maximum number of lines we defined
            {
                messages.RemoveAt(0);   // remove the first entry from the list
            }
            Refresh();  // call the refresh list method
        }


        /// <summary>
        /// Clears the message window
        /// </summary>
        public void Clear()
        { 
            messages.Clear();   // clear all entries from the list
            Refresh();  // call the refresh list method
        }

        #endregion

        #region ++++ private methods ++++

        // private method that refreshes the message window text
        private void Refresh()
        {
            if (outputSig == null) return;  // check to make sure OutputSig is not null, and handle if it is null
            if (messages.Count == 0)    // if no message entries to display, sends a carrage return to clear the window
                outputSig.StringValue = "\r";
            else
            {
                string temp = "";   // create an empty temp string
                foreach (string s in messages)  // loop that iterates through all the individual strings in the list
                {
                    temp += s;  // add the message to temp
                    temp += "\r";   // add a carrage return after the message
                }
                outputSig.StringValue = temp;   // set the serial feedback join to temp;
            }
        }

        #endregion

    }
}
