from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django import forms
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError

from .models import User, Auction, Bid, Comment, Watchlist

# ------------------------ Forms ------------------------

class CreateListingForm(forms.ModelForm):
    title = forms.CharField(max_length=20, required=True, widget=forms.TextInput(attrs={
        "autocomplete": "off", "aria-label": "title", "class": "form-control"
    }))
    description = forms.CharField(widget=forms.Textarea(attrs={
        'placeholder': "Tell more about the product", "aria-label": "description", "class": "form-control"
    }))
    image_url = forms.URLField(required=True, widget=forms.URLInput(attrs={"class": "form-control"}))
    category = forms.ChoiceField(required=True, choices=Auction.CATEGORY, widget=forms.Select(attrs={"class": "form-control"}))

    class Meta:
        model = Auction
        fields = ["title", "description", "category", "image_url"]

class BidForm(forms.ModelForm):
    class Meta:
        model = Bid
        fields = ["bid_price"]
        labels = {"bid_price": _("")}
        widgets = {
            "bid_price": forms.NumberInput(attrs={"placeholder": "Bid", "min": 0.01, "class": "form-control"})
        }

class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["comment"]
        labels = {"comment": _("")}
        widgets = {
            "comment": forms.Textarea(attrs={"placeholder": "Comment here", "class": "form-control", "rows": 1})
        }

# ------------------------ Authentication Views ------------------------

def login_view(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return HttpResponseRedirect(reverse("auctions:index"))
        else:
            return render(request, "auctions/login.html", {
                "message": "Invalid username and/or password."
            })
    return render(request, "auctions/login.html")

def logout_view(request):
    logout(request)
    return HttpResponseRedirect(reverse("auctions:index"))

def register(request):
    if request.method == "POST":
        username = request.POST["username"]
        email = request.POST["email"]
        password = request.POST["password"]
        confirmation = request.POST["confirmation"]
        if password != confirmation:
            return render(request, "auctions/register.html", {
                "message": "Passwords must match."
            })
        try:
            user = User.objects.create_user(username, email, password)
            user.save()
        except IntegrityError:
            return render(request, "auctions/register.html", {
                "message": "Username already taken."
            })
        login(request, user)
        return HttpResponseRedirect(reverse("auctions:index"))
    return render(request, "auctions/register.html")

# ------------------------ Auction Views ------------------------

def index(request):
    auctions = Auction.objects.filter(closed=False).order_by("-publication_date")
    return render(request, "auctions/index.html", {"auctions": auctions})

@login_required(login_url="auctions:login")
def user_panel(request):
    all_distinct_bids =  Bid.objects.filter(user=request.user.id).values_list("auction", flat=True).distinct()
    won = []
    selling = Auction.objects.filter(closed=False, seller=request.user.id).order_by("-publication_date")
    sold = Auction.objects.filter(closed=True, seller=request.user.id).order_by("-publication_date")
    bidding = Auction.objects.filter(closed=False, id__in=all_distinct_bids)
    for auction in Auction.objects.filter(closed=True, id__in=all_distinct_bids):
        highest_bid = Bid.objects.filter(auction=auction.id).order_by('-bid_price').first()
        if highest_bid and highest_bid.user.id == request.user.id:
            won.append(auction)
    return render(request, "auctions/user_panel.html", {
        "selling": selling, "sold": sold, "bidding": bidding, "won": won
    })

@login_required(login_url="auctions:login")
def create_listing(request):
    if request.method == "POST":
        form = CreateListingForm(request.POST)
        if form.is_valid():
            auction = form.save(commit=False)
            auction.seller = request.user
            auction.save()
            return HttpResponseRedirect(reverse("auctions:index"))
        return render(request, "auctions/create_listing.html", {"form": form})
    return render(request, "auctions/create_listing.html", {"form": CreateListingForm()})

def listing_page(request, auction_id):
    try:
        auction = Auction.objects.get(pk=auction_id)
    except Auction.DoesNotExist:
        return render(request, "auctions/error_handling.html", {"code": 404, "message": "Auction id doesn't exist"})
    bid_amount = Bid.objects.filter(auction=auction_id).count()
    highest_bid = Bid.objects.filter(auction=auction_id).order_by('-bid_price').first()
    if auction.closed:
        if highest_bid:
            winner = highest_bid.user
            if request.user.is_authenticated and request.user.id == auction.seller.id:
                return render(request, "auctions/sold.html", {"auction": auction, "winner": winner})
            elif request.user.is_authenticated and request.user.id == winner.id:
                return render(request, "auctions/bought.html", {"auction": auction})
        elif request.user.is_authenticated and request.user.id == auction.seller.id:
            return render(request, "auctions/closed_no_offer.html", {"auction": auction})
        return render(request, "auctions/error_handling.html", {"code": 403, "message": "This auction is closed."})
    on_watchlist = False
    if request.user.is_authenticated:
        on_watchlist = Watchlist.objects.filter(auction=auction_id, user=request.user).exists()
    comments = Comment.objects.filter(auction=auction_id).order_by("-comment_date")
    bid_message = "Be the first to bid!"
    if highest_bid:
        bid_message = "Your bid is the highest bid" if request.user.is_authenticated and highest_bid.user == request.user else f"Highest bid made by {highest_bid.user.username}"
    return render(request, "auctions/listing_page.html", {
        "auction": auction, "bid_amount": bid_amount, "bid_message": bid_message,
        "on_watchlist": on_watchlist, "comments": comments,
        "bid_form": BidForm(), "comment_form": CommentForm()
    })

@login_required(login_url="auctions:login")
def watchlist(request):
    if request.method == "POST":
        auction_id = request.POST.get("auction_id")
        try:
            auction = Auction.objects.get(pk=auction_id)
        except Auction.DoesNotExist:
            return render(request, "auctions/error_handling.html", {"code": 404, "message": "Auction not found"})
        if request.POST.get("on_watchlist") == "True":
            Watchlist.objects.filter(user=request.user, auction=auction).delete()
        else:
            try:
                Watchlist.objects.create(user=request.user, auction=auction)
            except IntegrityError:
                return render(request, "auctions/error_handling.html", {"code": 400, "message": "Already in watchlist"})
        return HttpResponseRedirect(request.POST.get("next", "/" + auction_id))
    ids = request.user.watchlist.values_list("auction", flat=True)
    items = Auction.objects.filter(id__in=ids, closed=False)
    return render(request, "auctions/watchlist.html", {"watchlist_items": items})

@login_required(login_url="auctions:login")
def bid(request):
    if request.method == "POST":
        form = BidForm(request.POST)
        if form.is_valid():
            bid_price = float(form.cleaned_data["bid_price"])
            auction_id = request.POST.get("auction_id")
            try:
                auction = Auction.objects.get(pk=auction_id)
            except Auction.DoesNotExist:
                return render(request, "auctions/error_handling.html", {"code": 404, "message": "Auction not found"})
            if auction.seller == request.user:
                return render(request, "auctions/error_handling.html", {"code": 400, "message": "Seller cannot bid."})
            highest_bid = Bid.objects.filter(auction=auction).order_by('-bid_price').first()
            if not highest_bid or bid_price > highest_bid.bid_price:
                Bid.objects.create(auction=auction, user=request.user, bid_price=bid_price)
                auction.current_price = bid_price
                auction.save()
                return HttpResponseRedirect("/" + auction_id)
            return render(request, "auctions/error_handling.html", {"code": 400, "message": "Bid too low."})
        return render(request, "auctions/error_handling.html", {"code": 400, "message": "Invalid bid"})
    return render(request, "auctions/error_handling.html", {"code": 405, "message": "Method not allowed"})

def categories(request, category=None):
    categories_list = Auction.CATEGORY
    if category:
        if category in [c[0] for c in categories_list]:
            category_full = dict(categories_list)[category]
            auctions = Auction.objects.filter(category=category, closed=False)
            return render(request, "auctions/category.html", {"auctions": auctions, "category_full": category_full})
        return render(request, "auctions/error_handling.html", {"code": 400, "message": "Invalid category"})
    return render(request, "auctions/error_handling.html", {"code": 404, "message": "Category not specified"})

@login_required(login_url="auctions:login")
def close_auction(request, auction_id):
    try:
        auction = Auction.objects.get(pk=auction_id)
    except Auction.DoesNotExist:
        return render(request, "auctions/error_handling.html", {"code": 404, "message": "Auction not found"})
    if request.method == "POST":
        if request.user != auction.seller:
            return render(request, "auctions/error_handling.html", {"code": 403, "message": "Unauthorized"})
        auction.closed = True
        auction.save()
        return HttpResponseRedirect(reverse("auctions:listing_page", args=[auction_id]))
    return render(request, "auctions/error_handling.html", {"code": 405, "message": "Only POST allowed"})

@login_required(login_url="auctions:login")
def handle_comment(request, auction_id):
    if request.method == "POST":
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.cleaned_data["comment"]
            try:
                auction = Auction.objects.get(pk=auction_id)
            except Auction.DoesNotExist:
                return render(request, "auctions/error_handling.html", {"code": 404, "message": "Auction not found"})
            Comment.objects.create(user=request.user, auction=auction, comment=comment)
            return HttpResponseRedirect(reverse("auctions:listing_page", args=[auction_id]))
        return render(request, "auctions/error_handling.html", {"code": 400, "message": "Invalid comment"})
    return render(request, "auctions/error_handling.html", {"code": 405, "message": "Only POST allowed"})
