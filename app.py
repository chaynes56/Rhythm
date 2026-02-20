# from https://github.com/plotly/tutorial-code/blob/main/Videos/DashIntro/app.py as part of
# https://www.youtube.com/watch?v=0mfIK8zxUds&t=1s&ab_channel=Plotly tutorial on Dash by Plotly.
# This code creates a Dash application that visualizes Airbnb listings in Mexico City.
# It allows users to filter listings based on minimum nights and price range,
# and displays the results on a scatter mapbox. The data is sourced from a CSV file hosted on GitHub,
# which contains information about Airbnb listings in Mexico City. The application uses Plotly Express for visualization
# and Dash Bootstrap Components for styling.

from dash import Dash, dcc, html, Output, Input
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd

# https://www.kaggle.com/datasets/tsarina/mexico-city-airbnb?select=listings1.csv
df = pd.read_csv("https://raw.githubusercontent.com/Coding-with-Adam/Dash-by-Plotly/master/Other/Monterrey/airbnb.csv")
print(df.iloc[:5, 5:8])

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])  # https://dashcheatsheet.pythonanywhere.com/

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col([
            dcc.Markdown('# Mexico DF Airbnb Analysis', style={'textAlign': 'center'})
        ], width=12)
    ]),

    dbc.Row([
        dbc.Col([
            dcc.Markdown('#### Select minimum Nights'),
            night_input := dcc.Input(type='number', value=3, min=1, max=30)
        ], width=6),

        dbc.Col([
            dcc.Markdown('#### Select price range'),
            price_slider := dcc.RangeSlider(min=df.price.min(), max=10000, value=[0, 2500], step=500,
                                            marks={'0': '0', '500': '500', '1000': '1000',
                                                   '2500': '2500', '5000': '5000',
                                                   '7500': '7500', '10000': '10000'},
                                            tooltip={"placement": "bottom", "always_visible": True}
                                            )
        ], width=6)
    ]),

    dbc.Row([
        dbc.Col([
            gr := dcc.Graph(figure={})
        ], width=12)
    ])
])


@app.callback(
    Output(gr, component_property='figure'),
    Input(night_input, 'value'),
    Input(price_slider, 'value')
)
def update_graph(nights_value, prices_value):
    print(nights_value)
    print(prices_value)
    dff = df[df.minimum_nights >= nights_value]
    dff = dff[(dff.price > prices_value[0]) & (dff.price < prices_value[1])]

    fig = px.scatter_mapbox(data_frame=dff, lat='latitude', lon='longitude', color='price', height=600,
                            range_color=[0, 1000], zoom=11, color_continuous_scale=px.colors.sequential.Sunset,
                            hover_data={'latitude': False, 'longitude': False, 'room_type': True,
                                        'minimum_nights': True})
    fig.update_layout(mapbox_style='carto-positron')

    return fig


if __name__ == '__main__':
    # to avoid conflict with other Dash apps running on the same machine. Change port if needed.
    app.run(debug=True, port=8006) # run, not run_server